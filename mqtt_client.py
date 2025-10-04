import json
import logging
import paho.mqtt.client as mqtt
import threading
from typing import Callable, Dict, Any


class MQTTClient:
    """Handles MQTT communication with Home Assistant."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize MQTT client.
        
        Args:
            config: MQTT configuration dictionary
        """
        self.config = config
        self.broker = config.get("broker", "localhost")
        self.port = config.get("port", 1883)
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.topic_prefix = config.get("topic_prefix", "tablet")
        
        self.client = mqtt.Client(client_id="tablet-ha-app")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        
        self.is_connected = False
        self.message_callbacks: Dict[str, Callable] = {}
        
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
    
    def connect(self):
        """Connect to MQTT broker."""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            logging.info(f"Connecting to MQTT broker at {self.broker}:{self.port}")
        except Exception as e:
            logging.error(f"Error connecting to MQTT broker: {e}")
    
    def disconnect(self):
        """Disconnect from MQTT broker."""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logging.info("Disconnected from MQTT broker")
        except Exception as e:
            logging.error(f"Error disconnecting from MQTT broker: {e}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            self.is_connected = True
            logging.info("Connected to MQTT broker")
            
            # Subscribe to command topics
            topics = [
                f"{self.topic_prefix}/command/brightness",
                f"{self.topic_prefix}/command/screen",
                f"{self.topic_prefix}/command/switch_app",
                f"{self.topic_prefix}/command/presence_detection"
            ]
            
            for topic in topics:
                self.client.subscribe(topic)
                logging.debug(f"Subscribed to {topic}")
            
            # Publish availability
            self.publish_state("availability", "online")
        else:
            logging.error(f"Failed to connect to MQTT broker, return code: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        self.is_connected = False
        logging.warning(f"Disconnected from MQTT broker, return code: {rc}")
    
    def _on_message(self, client, userdata, msg):
        """Callback when message received."""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        
        logging.debug(f"Received message on {topic}: {payload}")
        
        # Extract command type from topic
        if topic.startswith(f"{self.topic_prefix}/command/"):
            command_type = topic.split("/")[-1]
            
            # Call registered callback if exists
            if command_type in self.message_callbacks:
                try:
                    self.message_callbacks[command_type](payload)
                except Exception as e:
                    logging.error(f"Error in message callback for {command_type}: {e}", exc_info=True)
    
    def register_callback(self, command_type: str, callback: Callable[[str], None]):
        """
        Register a callback for a specific command type.
        
        Args:
            command_type: Command type (e.g., 'brightness', 'screen')
            callback: Function to call when command received
        """
        self.message_callbacks[command_type] = callback
    
    def publish_state(self, state_type: str, value: Any):
        """
        Publish state to MQTT.
        
        Args:
            state_type: Type of state (e.g., 'presence', 'brightness')
            value: Value to publish
        """
        try:
            topic = f"{self.topic_prefix}/state/{state_type}"
            
            # Convert value to string
            if isinstance(value, (dict, list)):
                payload = json.dumps(value)
            else:
                payload = str(value)
            
            self.client.publish(topic, payload, retain=True)
        except Exception as e:
            logging.error(f"Error publishing state: {e}")
    
    def publish_discovery_config(self):
        """Publish Home Assistant MQTT discovery configuration."""
        try:
            device_info = {
                "identifiers": ["tablet-ha"],
                "name": "Tablet HA",
                "model": "Windows Tablet",
                "manufacturer": "Custom"
            }
            
            # Presence sensor
            presence_config = {
                "name": "Tablet Presence",
                "state_topic": f"{self.topic_prefix}/state/presence",
                "payload_on": "detected",
                "payload_off": "not_detected",
                "device_class": "occupancy",
                "device": device_info,
                "unique_id": "tablet_ha_presence"
            }
            self.client.publish(
                f"homeassistant/binary_sensor/tablet_ha/presence/config",
                json.dumps(presence_config),
                retain=True
            )
            
            # Brightness sensor
            brightness_config = {
                "name": "Tablet Brightness",
                "state_topic": f"{self.topic_prefix}/state/brightness",
                "command_topic": f"{self.topic_prefix}/command/brightness",
                "unit_of_measurement": "%",
                "device": device_info,
                "unique_id": "tablet_ha_brightness"
            }
            self.client.publish(
                f"homeassistant/sensor/tablet_ha/brightness/config",
                json.dumps(brightness_config),
                retain=True
            )
            
            logging.info("Published MQTT discovery configuration")
        except Exception as e:
            logging.error(f"Error publishing discovery config: {e}")
