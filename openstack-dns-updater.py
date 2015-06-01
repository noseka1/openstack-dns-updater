#!/usr/bin/env python

# OpenStack DNS Updater listens on the RabbitMQ message bus. Whenever an
# instance is created or deleted DNS updater creates or removes
# its DNS A record. The name of the instance is directly used as its FQDN.
# Hence instances in OpenStack should be named with their FQDN.
# The IP address stored in DNS is the IP address of the first network interface
# on the private network. You can easily change the script to store floating
# IP address in DNS instead.
#
# OpenStack DNS Updater works well on CentOS 7. You can copy it into your
# /usr/local/bin directory and run it as user "nova". See the accompanying
# systemd script. OpenStack DNS Updater logs into /var/log/nova/dns-updater.log
# by default.

import json
import logging as log
from subprocess import Popen, PIPE
from kombu import BrokerConnection
from kombu import Exchange
from kombu import Queue
from kombu.mixins import ConsumerMixin

LOG_FILE="/var/log/nova/dns-updater.log"

EXCHANGE_NAME="nova"
ROUTING_KEY="notifications.info"
QUEUE_NAME="dns_updater"
BROKER_URI="amqp://guest:guest@localhost:5672//"
EVENT_CREATE="compute.instance.create.end"
EVENT_DELETE="compute.instance.delete.start"

NAMESERVER="ns.localdomain.com"
TTL=1
NSUPDATE_ADD="\
server {nameserver}\n\
update delete {hostname} A\n\
update add {hostname} {ttl} A {hostaddr}\n\
send"

NSUPDATE_DEL="\
server {nameserver}\n\
update delete {hostname} A\n\
send"

log.basicConfig(filename=LOG_FILE, level=log.INFO,
    format='%(asctime)s %(message)s')

class DnsUpdater(ConsumerMixin):

    def __init__(self, connection):
        self.connection = connection
        return

    def get_consumers(self, consumer, channel):
        exchange = Exchange(EXCHANGE_NAME, type="topic", durable=False)
        queue = Queue(QUEUE_NAME, exchange, routing_key = ROUTING_KEY,
            durable=False, auto_delete=True, no_ack=True)
        return [ consumer(queue, callbacks = [ self.on_message ]) ]

    def on_message(self, body, message):
        try:
            self._handle_message(body)
        except Exception, e:
            log.info(repr(e))

    def _handle_message(self, body):
        log.debug('Body: %r' % body)
        jbody = json.loads(body["oslo.message"])
        event_type = jbody["event_type"]
        if event_type in [ EVENT_CREATE, EVENT_DELETE ]:
            hostname = jbody["payload"]["hostname"]
            if event_type == EVENT_CREATE:
                hostaddr = jbody["payload"]["fixed_ips"][0]["address"]
                nsupdate_script = NSUPDATE_ADD
                log.info("Adding {} {}".format(hostname, hostaddr))
            else:
                hostaddr=""
                nsupdate_script = NSUPDATE_DEL
                log.info("Deleting {}".format(hostname))
            p = Popen(['nsupdate'], stdin=PIPE)
            input = nsupdate_script.format(nameserver=NAMESERVER,
                hostname=hostname, ttl=TTL, hostaddr=hostaddr)
            p.communicate(input=input)

if __name__ == "__main__":
    log.info("Connecting to broker {}".format(BROKER_URI))
    with BrokerConnection(BROKER_URI) as connection:
        DnsUpdater(connection).run()
