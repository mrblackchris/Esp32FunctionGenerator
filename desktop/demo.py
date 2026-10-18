"""Explicit offline preview data; never connects to hardware."""
from copy import deepcopy
import math
import time


class DemoClient:
    def __init__(self, _port=''):
        self.channels = []
        self.started = {}
        for i, (high, low) in enumerate([(18, 19), (21, 22), (23, 32), (25, -1), (26, -1)]):
            self.channels.append(dict(id=i, highPin=high, lowPin=low, enabled=False, mode='pulse',
                                      frequency=1000, duty=50, deadUs=1, onUs=20, offUs=80,
                                      pulseCount=10, burstCount=1, gapMs=100, completedBursts=0,
                                      waveHz=100, amplitude=50, internalTest=False))
        self.network = dict(ssid='Your Wi-Fi network', passwordSet=True, dhcp=True,
                            connected=True, currentIP='192.168.1.100', currentGateway='192.168.1.1',
                            currentSubnet='255.255.255.0', currentDns='192.168.1.1',
                            ip='0.0.0.0', gateway='0.0.0.0', subnet='0.0.0.0', dns='0.0.0.0')

    def close(self):
        pass

    def request(self, path, params=None, timeout=6):
        p = params or {}
        if path == '/network/set':
            self.network.update({k: p[k] for k in ('ssid', 'ip', 'gateway', 'subnet', 'dns') if k in p})
            self.network['dhcp'] = p['dhcp'] == '1'
            if p['replacePassword'] == '1':
                self.network['passwordSet'] = bool(p['password'])
            self.network['currentIP'] = '192.168.1.100' if self.network['dhcp'] else self.network['ip']
        if path.startswith('/network'):
            return deepcopy(self.network)
        if path == '/set':
            c = self.channels[int(p['id'])]
            for key, value in p.items():
                if key == 'id':
                    continue
                c[key] = (value == '1') if key == 'enabled' else value if key == 'mode' else float(value)
            c['completedBursts'] = 0
            self.started.pop(c['id'], None)
        elif path == '/burst':
            i = int(p['id'])
            self.channels[i].update(enabled=True, completedBursts=0)
            self.started[i] = time.monotonic()
        elif path == '/stop':
            for c in self.channels:
                if p['id'] == 'all' or int(p['id']) == c['id']:
                    c['enabled'] = False
                    self.started.pop(c['id'], None)
        for c in self.channels:
            c.update(actualHz=c['frequency'] if c['id'] < 3 else 1e6 / (c['onUs'] + c['offUs']),
                     actualDuty=c['duty'] if c['id'] < 3 else 100 * c['onUs'] / (c['onUs'] + c['offUs']),
                     actualDeadUs=c['deadUs'], actualWaveHz=math.floor(c['waveHz'] * 4096 / 40000 + .5) * 40000 / 4096)
            loss = c['deadUs'] * c['actualHz'] / 10000
            c.update(highDuty=max(0, c['duty'] - loss), lowDuty=max(0, 100 - c['duty'] - loss))
            if c['id'] in self.started:
                duration = (c['onUs'] + c['offUs']) * c['pulseCount'] / 1e6 + c['gapMs'] / 1000
                done = min(c['burstCount'], int((time.monotonic() - self.started[c['id']]) / duration))
                c['completedBursts'] = done
                if done == c['burstCount']:
                    c['enabled'] = False
                    self.started.pop(c['id'])
        return deepcopy(self.channels)
