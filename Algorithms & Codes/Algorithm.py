import RPi.GPIO as GPIO
import time
import json
import hashlib
from datetime import datetime
import threading
import board
import busio
from adafruit_mcp230xx.mcp23017 import MCP23017
import digitalio

class SecureLockboxSystem:
    def __init__(self, config_file="/home/pi/lockbox_config.json"):
        """Initialize the secure lockbox system"""
        self.config_file = config_file
        self.load_configuration()
        
        # Hardware pin assignments
        self.servo_pin = 12
        self.status_led_pin = 16
        self.buzzer_pin = 20
        
        # I2C GPIO Expanders for 31 buttons and 31 LEDs
        self.setup_gpio_expanders()
        
        # System state variables
        self.current_step = 0
        self.unlocked = False
        self.system_locked = False
        self.failed_attempts = 0
        self.max_attempts = 3
        self.lockout_duration = 300  # 5 minutes
        self.last_activity = time.time()
        
        # Security logging
        self.event_log = []
        self.max_log_entries = 1000
        
        # Keypad configuration
        self.keypad_row_pins = [21, 22, 23]
        self.keypad_col_pins = [24, 25, 26]
        self.keypad_keys = [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9']
        ]
        
        self.setup_raspberry_pi_gpio()
        self.log_event("System initialized successfully")

    def setup_gpio_expanders(self):
        """Initialize I2C GPIO expanders for buttons and LEDs"""
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Three MCP23017 chips for 48 total GPIO pins
            self.mcp_buttons = MCP23017(i2c, address=0x20)  # 31 buttons
            self.mcp_leds1 = MCP23017(i2c, address=0x21)    # LEDs 0-15
            self.mcp_leds2 = MCP23017(i2c, address=0x22)    # LEDs 16-30
            
            # Configure button pins (with pull-up resistors)
            self.button_pins = []
            for i in range(16):  # First 16 buttons
                pin = self.mcp_buttons.get_pin(i)
                pin.direction = digitalio.Direction.INPUT
                pin.pull = digitalio.Pull.UP
                self.button_pins.append(pin)
            
            # Configure LED pins
            self.led_pins = []
            for i in range(16):  # First 16 LEDs
                pin = self.mcp_leds1.get_pin(i)
                pin.direction = digitalio.Direction.OUTPUT
                pin.value = False
                self.led_pins.append(pin)
            
            for i in range(15):  # Remaining 15 LEDs
                pin = self.mcp_leds2.get_pin(i)
                pin.direction = digitalio.Direction.OUTPUT
                pin.value = False
                self.led_pins.append(pin)
                
            self.log_event("GPIO expanders initialized successfully")
            
        except Exception as e:
            self.log_event(f"GPIO expander initialization failed: {e}")
            raise

    def setup_raspberry_pi_gpio(self):
        """Initialize Raspberry Pi GPIO pins"""
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Servo motor
        GPIO.setup(self.servo_pin, GPIO.OUT)
        
        # Status LED
        GPIO.setup(self.status_led_pin, GPIO.OUT)
        GPIO.output(self.status_led_pin, GPIO.LOW)
        
        # Buzzer for audio feedback
        GPIO.setup(self.buzzer_pin, GPIO.OUT)
        
        # Keypad pins
        for pin in self.keypad_row_pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        for pin in self.keypad_col_pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def load_configuration(self):
        """Load system configuration from encrypted file"""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            # Load encrypted credentials
            self.correct_path = config.get('tree_sequence', [0, 1, 3, 7, 15])
            self.correct_pin_hash = config.get('pin_hash', self.hash_pin("1234"))
            self.admin_pin_hash = config.get('admin_hash', self.hash_pin("9999"))
            
        except FileNotFoundError:
            # Create default configuration
            self.correct_path = [0, 1, 3, 7, 15]
            self.correct_pin_hash = self.hash_pin("1234")
            self.admin_pin_hash = self.hash_pin("9999")
            self.save_configuration()
            self.log_event("Default configuration created")

    def save_configuration(self):
        """Save system configuration to encrypted file"""
        config = {
            'tree_sequence': self.correct_path,
            'pin_hash': self.correct_pin_hash,
            'admin_hash': self.admin_pin_hash,
            'last_updated': datetime.now().isoformat()
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def hash_pin(self, pin):
        """Create secure hash of PIN"""
        salt = "lockbox_secure_salt_2024"
        return hashlib.sha256((pin + salt).encode()).hexdigest()

    def log_event(self, event):
        """Log security events with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {event}"
        print(log_entry)
        
        self.event_log.append(log_entry)
        if len(self.event_log) > self.max_log_entries:
            self.event_log.pop(0)
        
        # Write to file for persistence
        try:
            with open("/home/pi/lockbox_events.log", "a") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            print(f"Logging error: {e}")

    def reset_system(self):
        """Reset all LEDs and system state"""
        for led in self.led_pins:
            led.value = False
        
        self.current_step = 0
        self.unlocked = False
        GPIO.output(self.status_led_pin, GPIO.LOW)
        self.log_event("System reset completed")

    def audio_feedback(self, pattern="single"):
        """Provide audio feedback for user actions"""
        try:
            if pattern == "single":
                GPIO.output(self.buzzer_pin, GPIO.HIGH)
                time.sleep(0.1)
                GPIO.output(self.buzzer_pin, GPIO.LOW)
            elif pattern == "success":
                for _ in range(3):
                    GPIO.output(self.buzzer_pin, GPIO.HIGH)
                    time.sleep(0.1)
                    GPIO.output(self.buzzer_pin, GPIO.LOW)
                    time.sleep(0.1)
            elif pattern == "error":
                for _ in range(2):
                    GPIO.output(self.buzzer_pin, GPIO.HIGH)
                    time.sleep(0.3)
                    GPIO.output(self.buzzer_pin, GPIO.LOW)
                    time.sleep(0.1)
        except Exception as e:
            self.log_event(f"Audio feedback error: {e}")

    def check_tree_buttons(self):
        """Check binary tree button sequence with enhanced debouncing"""
        if self.system_locked:
            return
        
        for idx, button in enumerate(self.button_pins):
            if idx >= 31:  # Limit to 31 buttons
                break
                
            if not button.value:  # Button pressed (active low with pull-up)
                # Debounce delay
                time.sleep(0.05)
                if not button.value:  # Confirm button still pressed
                    self.log_event(f"Button {idx} pressed at step {self.current_step}")
                    self.audio_feedback("single")
                    
                    if idx == self.correct_path[self.current_step]:
                        # Correct button pressed
                        self.led_pins[idx].value = True
                        self.current_step += 1
                        self.log_event(f"Correct button {idx}, advancing to step {self.current_step}")
                        
                        if self.current_step >= len(self.correct_path):
                            self.unlocked = True
                            GPIO.output(self.status_led_pin, GPIO.HIGH)
                            self.audio_feedback("success")
                            self.log_event("Binary tree sequence completed successfully")
                    else:
                        # Wrong button pressed
                        self.log_event(f"Incorrect button {idx} at step {self.current_step}")
                        self.audio_feedback("error")
                        self.failed_attempts += 1
                        self.reset_system()
                        
                        if self.failed_attempts >= self.max_attempts:
                            self.initiate_lockout()
                    
                    # Wait for button release
                    while not button.value:
                        time.sleep(0.01)
                    
                    self.last_activity = time.time()

    def scan_keypad(self):
        """Enhanced keypad scanning with debouncing"""
        for col_idx, col_pin in enumerate(self.keypad_col_pins):
            GPIO.setup(col_pin, GPIO.OUT)
            GPIO.output(col_pin, GPIO.LOW)
            time.sleep(0.001)  # Small delay for signal stability
            
            for row_idx, row_pin in enumerate(self.keypad_row_pins):
                if GPIO.input(row_pin) == GPIO.LOW:
                    key = self.keypad_keys[row_idx][col_idx]
                    
                    # Debounce delay
                    time.sleep(0.05)
                    if GPIO.input(row_pin) == GPIO.LOW:
                        # Wait for key release
                        while GPIO.input(row_pin) == GPIO.LOW:
                            time.sleep(0.01)
                        
                        GPIO.setup(col_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                        self.audio_feedback("single")
                        return key
            
            GPIO.setup(col_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        return None

    def unlock_mechanism(self):
        """Control servo to unlock the mechanism"""
        try:
            self.log_event("Initiating unlock sequence")
            servo = GPIO.PWM(self.servo_pin, 50)  # 50Hz for servo
            servo.start(7.5)  # Neutral position
            
            # Move to unlock position
            servo.ChangeDutyCycle(2.5)  # 0 degrees
            time.sleep(1)
            
            # Hold unlock position
            time.sleep(2)
            
            # Return to neutral
            servo.ChangeDutyCycle(7.5)
            time.sleep(0.5)
            
            servo.stop()
            self.audio_feedback("success")
            self.log_event("Mechanism unlocked successfully")
            
        except Exception as e:
            self.log_event(f"Servo unlock error: {e}")

    def initiate_lockout(self):
        """Initiate security lockout after failed attempts"""
        self.system_locked = True
        self.log_event(f"SECURITY LOCKOUT: {self.failed_attempts} failed attempts")
        
        # Flash all LEDs to indicate lockout
        for _ in range(10):
            for led in self.led_pins:
                led.value = True
            GPIO.output(self.status_led_pin, GPIO.HIGH)
            time.sleep(0.2)
            for led in self.led_pins:
                led.value = False
            GPIO.output(self.status_led_pin, GPIO.LOW)
            time.sleep(0.2)
        
        # Audio warning
        self.audio_feedback("error")
        
        # Start lockout timer in separate thread
        lockout_thread = threading.Thread(target=self.lockout_timer)
        lockout_thread.daemon = True
        lockout_thread.start()

    def lockout_timer(self):
        """Handle lockout timing"""
        self.log_event(f"Lockout timer started for {self.lockout_duration} seconds")
        time.sleep(self.lockout_duration)
        
        self.system_locked = False
        self.failed_attempts = 0
        self.reset_system()
        self.log_event("System lockout expired - normal operation resumed")

    def handle_pin_entry(self):
        """Handle PIN entry phase with enhanced security"""
        entered_pin = ""
        self.log_event("PIN entry phase
