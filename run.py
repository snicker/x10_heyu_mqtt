#!/usr/bin/env python3

import logging
import signal
import threading
import time
import traceback

import paho.mqtt.client as mqtt

import heyu
import settings

__author__ = 'madrider'

LOG = logging.getLogger(__name__)


def match_topic(mask, topic):
    mask_parts = mask.split('/')
    topic_parts = topic.split('/')

    if mask_parts[0] == '#':
        return True

    if len(topic_parts) < len(mask_parts):
        return False

    for m, t in zip(mask_parts, topic_parts):
        if m == '+':
            continue
        if m == '#':
            return True
        if t != m:
            return False
    return True


class X10Tester(threading.Thread):
    resend_timeout = settings.x10_status_update_interval
    commands = []
    status = {}
    time = {}

    def __init__(self, publisher):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.__gen = self.__next_command_generator()
        self.publisher = publisher

    def __next_command_generator(self):
        while 1:
            for d in settings.x10_switches:
                while self.commands:
                    yield self.commands.pop()
                if d is not None:
                    yield (d, 'status')

    def run(self):
        while 1:
            self.cycle()
            time.sleep(0.01)

    def add_command(self, cmd):
        i = 0
        for c in self.commands[:]:
            if c[0] == cmd[0]:
                i += 1
                self.commands.remove(c)
        if i:
            LOG.warn('removing %s commands for %s', i, cmd[0])
        self.commands.append(cmd)

    def cycle(self):
        addr, cmd = self.__gen.__next__()

        LOG.debug(cmd)
        if cmd == 'status':
            status = heyu.get_status(addr)
            if status:
                LOG.debug('status of %s is %s', addr, status)
                if self.status.get(addr) != status:
                    self.publish(addr, status)
                elif time.time() - self.time.get(addr, 0) > self.resend_timeout:
                    self.publish(addr, status)
        else:
            heyu.send_command(cmd, addr)

    def publish(self, addr, status):
        self.status[addr] = status
        self.time[addr] = time.time()
        self.publisher.publish('x10/%s' % addr.lower(), status, qos=0, retain=False)

class Main(object):
    server = '127.0.0.1'
    port = 1883
    user = None
    password = None
    pause = 0.5

    def __init__(self, server=None, port=None, user=None, password=None):
        signal.signal(signal.SIGUSR1, self.debug)
        self.topics = {'x10/+/command': self.x10_cmd}
        if server:
            self.server = server
        if port:
            self.port = port
        if user:
            self.user = user
        if password:
            self.password = password
        self.client = mqtt.Client()
        self.x10_tester = X10Tester(self)

    def on_connect(self, client, userdata, flags, rc):
        LOG.info('Connected with result code %s', rc)
        for topic in self.topics:
            client.subscribe([(topic, 0), (topic, 1)])

    def on_disconnect(self, client, userdata, rc):
        LOG.info('disconnect with %s', rc)

    def on_message(self, client, userdata, msg):
        if msg.retain:
            return
        LOG.info('message to topic %s', msg.topic)
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        for t, cmd in self.topics.items():
            if match_topic(t, topic):
                try:
                    cmd(topic, payload)
                except:
                    LOG.exception('')
                break

    def x10_cmd(self, topic, payload):
        parts = topic.split('/')
        if parts[2] == 'command':
            cmd = payload.lower()
            addr = parts[1]
            LOG.info('got cmd %s to %s', cmd, addr)
            self.x10_tester.add_command((addr, cmd))

    def debug(self, sig, stack):
        with open('running_stack', 'w') as f:
            f.write('Debug\n\n')
            traceback.print_stack(stack, file=f)

    def main(self):
        if self.user:
            self.client.username_pw_set(self.user, self.password)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.client.connect(self.server, self.port, 60)
        self.client.loop_start()
        try:
            self.x10_tester.start()
            while 1:
                time.sleep(1)

        finally:
            self.client.loop_stop()

    def publish(self, *args, **kw):
        LOG.debug('sending to %s', args[0])
        self.client.publish(*args, **kw)


if __name__ == '__main__':
    fh = logging.FileHandler('x10.log')
    fh.setLevel(logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)

    LOG.setLevel(logging.DEBUG)
    LOG.addHandler(fh)

    Main(server=settings.server, port=settings.port, user=settings.user, password=settings.password).main()
