import yaml

with open("settings.yaml","r") as f:
    settings_yaml = yaml.safe_load(f)

heyu_binary = settings_yaml.get('heyu_binary','/usr/local/bin/heyu')

mqtt_settings = settings_yaml.get('mqtt',{})

server = mqtt_settings.get('server','192.168.0.1')
port = mqtt_settings.get('port',1883)
user = mqtt_settings.get('user',None)
password = mqtt_settings.get('password',None)

x10_settings = settings_yaml.get('x10',{})

x10_switches = x10_settings.get('monitored_switches',[None])
x10_status_update_interval = x10_settings.get('status_update_interval',60)
