#!/usr/bin/env python3

import logging
import signal
import threading
import time
import traceback
import math

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
    brightness = {}

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
                    yield ['status', d]

    def run(self):
        while 1:
            self.cycle()
            time.sleep(0.01)

    def add_command(self, cmd):
        i = 0
        for c in self.commands[:]:
            if c == cmd:
                i += 1
                self.commands.remove(c)
        if i:
            LOG.warn('removing %s commands for %s', i, cmd)
        self.commands.append(cmd)

    def set_brightness(self, addr, brightness, is_rf=False):
        if brightness is not None and brightness > 0:
            current_brightness = self.brightness.get(addr,0)
            cur_step = math.ceil(current_brightness / 4.0)
            new_step = math.ceil(brightness / 4.0)
            delta = new_step - cur_step
            if delta != 0:
                command = "bright" if delta > 0 else "dim"
                rf = "f" if is_rf else ""
                step = abs(delta)
                self.add_command([f"{rf}{command}", f"{addr}", f"{step}"])
                self.brightness[addr] = (math.ceil(brightness /4.0) * 4) - 1

    def cycle(self):
        cmd = self.__gen.__next__()

        LOG.debug(cmd)
        addr = cmd[1]
        x10cmd = cmd[0]
        if 'status' in cmd:
            status = heyu.get_status(addr)
            if status:
                LOG.debug('status of %s is %s', addr, status)
                if self.status.get(addr) != status:
                    self.publish(addr, status)
                elif time.time() - self.time.get(addr, 0) > self.resend_timeout:
                    self.publish(addr, status)
        else:
            brightness_cmd = 'dim' in x10cmd or 'bright' in x10cmd
            timeout = 10
            if brightness_cmd:
                timeout = 20
            heyu.send_command_raw(" ".join(cmd), timeout=timeout)
            if brightness_cmd:
                self.publish(addr, 'on', self.brightness.get(addr))
            else:
                if "on" in x10cmd:
                    self.publish(addr, 'on')
                if "off" in x10cmd:
                    self.publish(addr, 'off')


    def publish(self, addr, status, brightness = None):
        self.status[addr] = status
        self.time[addr] = time.time()
        self.publisher.publish('x10/%s/status' % addr.lower(), status, qos=0, retain=False)
        if brightness:
            self.publisher.publish('x10/%s/status/brightness' % addr.lower(), brightness, qos=0, retain=False)

class Main(object):
    server = '127.0.0.1'
    port = 1883
    user = None
    password = None
    pause = 0.5

    def __init__(self, server=None, port=None, user=None, password=None):
        signal.signal(signal.SIGUSR1, self.debug)
        self.topics = {'x10/+/command': self.x10_cmd,
                        'x10/+/brightness': self.x10_brightness,
                        'x10/+/fbrightness': self.x10_brightness}
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
            self.x10_tester.add_command([cmd, addr])

    def x10_brightness(self, topic, payload):
        parts = topic.split('/')
        if parts[2] in ('brightness','fbrightness'):
            try:
                brightness = int(payload)
                addr = parts[1]
                rf = parts[2] == 'fbrightness'
                LOG.info('got %s %s to %s', parts[2], brightness, addr)
                return self.x10_tester.set_brightness(addr, brightness, rf)
            except Exception as e:
                LOG.exception('failed setting brightness for %s %s: %s' % (topic, payload, e))
                return None

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
