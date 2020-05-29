# x10_mqtt
x10 mqtt daemon that acts as a gate between mqtt x10 devices.
For x10 it uses [heyu binary](http://heyu.tanj.com/)

You can turn something on by sending 'ON' to `/x10/{addr}/command`, and listen status updates in `/x10/{addr}` if your X10 modules support getting status.
