broker_address= "192.168.2.53"
port = 8883
user = ""
password = ""

gas_topic = "gas_zaehler_umdrehung"
gas_model = "BK-G4"

data_file = "gas_zaehler_stand.txt"
update_file = "gas_zaehler_last_update.txt"


from fastapi import FastAPI
import paho.mqtt.client as mqttClient
import time
import os.path
import json
from datetime import datetime
import logging

logging.basicConfig(filename="gas.log",
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

logging.info("Starting Gas MQTT Reader...")

Connected = False #global variable for the state of the connection
  

# create storage files
if not os.path.exists(data_file):
    with open(data_file, "w") as f:
        f.write("0.0")
if not os.path.exists(update_file):
    with open(update_file, "w") as f:
        f.write("")        

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info(f"Connected to Broker {broker_address}/{gas_topic}")
  
        global Connected                #Use global variable
        Connected = True                #Signal connection 
    else:
  
        logging.error("Starting Gas MQTT Reader...")
  
def on_message(client, userdata, message):
    timestamp = datetime.now()
    if message and message.payload:
        byte_str = message.payload.decode('utf-8').replace("'", '"')
        json_payload = json.loads(byte_str)
        logging.debug(f"{timestamp} Received payload: {json_payload}")

        # update gas counter 
        current_value = None
        with open(data_file, "r") as f:
            current_value = (float)(f.read())

        new_value = current_value + 0.1

        with open(data_file, "w") as f:
            f.write(f"{new_value:.2f}")

        with open(update_file, "w") as f:
            f.write(f"{timestamp}")
                
    pass

client = mqttClient.Client("Python")               #create new instance
client.username_pw_set(user, password=password)    #set username and password
client.on_connect= on_connect                      #attach function to callback
client.on_message= on_message   
client.connect(broker_address, port=port)  #connect to broker
client.loop_start()                        #start the loop
  
# connect to MQTT broker
while Connected != True:
    time.sleep(0.1)

# listen on topic
client.subscribe(gas_topic)

logging.error("Starting REST API")
app = FastAPI()

@app.get("/")
async def root():
    current_value = None
    with open(data_file, "r") as f:
        current_value = (float)(f.read())
    
    last_update = None
    with open(update_file, "r") as f:
        last_update = f.read()

    logging.debug(f"Serving HTTP Request with Gas meter: {current_value}")
    
    return { 
        "model": gas_model,
        "meter": current_value,
        "last_update": last_update,
        "unit": "m3"
        }