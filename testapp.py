from dash import Dash, html, dcc, Input, Output, State
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
import pandas as pd
import plotly.express as px
import json

class InfluxDBHandler:
    def __init__(self, url, token, org, bucket_name):
        self.url = url
        self.token = token
        self.org = org
        self.bucket_name = bucket_name
        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()

    def write_data(self, measurement, tags, fields):
        point = Point(measurement)
        for key, value in tags.items():
            point.tag(key, value)
        for key, value in fields.items():
            point.field(key, value)
        self.write_api.write(bucket=self.bucket_name, org=self.org, record=point)

    def query_data(self, query):
        return self.query_api.query(org=self.org, query=query)

    def close(self):
        self.client.close()

class MQTTClient:
    def __init__(self, broker, port, keepalive, influxdb_handler):
        self.broker = broker
        self.port = port
        self.keepalive = keepalive
        self.influxdb_handler = influxdb_handler
        self.client = mqtt.Client()
        self.client.username_pw_set("gruppe1", "B4st4rd")
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def connect(self):
        self.client.connect(self.broker, self.port, self.keepalive)
        print(f"Connecting to broker {self.broker}:{self.port}")
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("Disconnected from broker")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Successfully connected to Mosquitto broker")
        else:
            print(f"Connection failed with result code {rc}")

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print("Unexpected disconnection.")
        else:
            print("Client disconnected successfully.")

    def publish_update(self, topic, payload):
        result = self.client.publish(topic, json.dumps(payload))
        status = result[0]
        if status == 0:
            print(f"Sent `{payload}` to topic `{topic}`")
        else:
            print(f"Failed to send message to topic {topic}")

# Configuration
broker_address = "34.32.61.227"
influxdb_handler = InfluxDBHandler(
    url="http://34.32.61.227:8086",
    token="6VcBU7_gCM3DavpNQFEZ_OAfODQBKZPvceX43FBKWAQExnfCDCH7VCA0SI2NkET9ZyJZ-ZhoRjtudxYTpGqxJg==",
    org="Gruppe1",
    bucket_name="MeowMate"
)
mqtt_client = MQTTClient(broker=broker_address, port=8883, keepalive=60, influxdb_handler=influxdb_handler)
mqtt_client.connect()

# App start
app = Dash(__name__)
app.title = "Meow Mate"

app.layout = html.Div(children=[
    html.H1("Velkommen til MeowMate"),
    html.H4("Din kat's bedste ven"),
    html.Label("Valg af sensor"),
    dcc.Dropdown(id='multi-sensor-dropdown', options=[], multi=True),
    html.Br(),

    dcc.Graph(id='sensor-graph'),
    html.Br(),
    
    html.Label("Indstillinger "),
    dcc.Input(id='update-key', type='text', placeholder='Tidspunkt'),
    dcc.Input(id='update-value', type='text', placeholder='Vægt'),
    html.Button('Opdater', id='update-button', n_clicks=0)
])

@app.callback(
    Output('multi-sensor-dropdown', 'options'),
    Input('update-button', 'n_clicks')
)
def update_sensor_options(n_clicks):
    query = '''
    from(bucket: "MeowMate")
      |> range(start: -30d)
      |> filter(fn: (r) => r._measurement == "sensor")
      |> keep(columns: ["location"])
      |> group(columns: ["location"])
      |> distinct(column: "location")
    '''
    tables = influxdb_handler.query_data(query)
    options = [] 
    
    for table in tables:
        for record in table.records:
            location = record.values.get("location")
            print(f"Location: {location}")  # Log each location
            options.append({'label': location, 'value': location})    
    print(f"Options: {options}")  # Log the final options list
    return options

@app.callback(
    Output('sensor-graph', 'figure'),
    Input('multi-sensor-dropdown', 'value')
)
def update_graph(sensors):
    if not sensors:
        return {}
    
    data = []
    
    for sensor in sensors:
        query = f'''
        from(bucket: "MeowMate")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "sensor" and r.location == "{sensor}")
          |> keep(columns: ["_time", "_value", "location"])
          |> yield(name: "sensor_data")
        '''    
        tables = influxdb_handler.query_data(query)
        
        for table in tables:
            for record in table.records:
                data.append({'time': record.values.get("_time").isoformat(), 'value': record.get_value(), 'sensor': sensor})
    
    df = pd.DataFrame(data)
    
    if df.empty:
        return {}
    fig = px.line(df, x='time', y='value', color='sensor', title='Sensor Data')
    fig.update_yaxes(title_text='Weight (grams)', rangemode="tozero")
    
    fig.update_layout(
        plot_bgcolor='#79655B',
        paper_bgcolor='#79655B',
        font=dict(color='#F2AC7D'),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False)
    )
    
    fig.update_traces(line=dict(color='#F2AC7D'))
    
    return fig

@app.callback(
    Output('update-key', 'value'),
    Output('update-value', 'value'),
    Input('update-button', 'n_clicks'),
    State('multi-sensor-dropdown', 'value'),
    State('update-key', 'value'),
    State('update-value', 'value')
)
def update_sensor_settings(n_clicks, sensor_ids, key, value):
    if n_clicks > 0 and sensor_ids and key and value:
        for sensor_id in sensor_ids:
            topic = f"{sensor_id}/setting/update"
            try:
                value_json = json.loads(value)  # Prøv at parse value som JSON
                payload = {"key": key, "value": value_json}
            except json.JSONDecodeError:
                payload = {"key": key, "value": value}
            
            mqtt_client.publish_update(topic=topic, payload=payload)
    return '', ''

if __name__ == '__main__':
    app.run_server(debug=True)