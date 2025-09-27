from bluepy import btle
import time
import codecs
import logging
import bmsstate

OUTGOING_HEADER = b'\xaa\x55\x90\xeb'
INCOMING_HEADER = b'\x55\xaa\xeb\x90'

MAX_COMMAND_TIMEOUT_SECONDS = 5
MAX_STATE_LIFE_SECCONDS = 5

COMMAND_REQ_EXTENDED_RECORD = 0x96
COMMAND_REQ_DEVICE_INFO = 0x97
COMMAND_REQ_CHARGE_SWITCH = 0x1d
COMMAND_REQ_DISCHARGE_SWITCH = 0x1e

RESPONSE_ACK = 0xc8
RESPONSE_EXTENDED_RECORD = 0x01
RESPONSE_CELL_DATA = 0x02
RESPONSE_DEVICE_INFO_RECORD = 0x03

class JkBMS(btle.DefaultDelegate):

    def __init__(self, bt_mac):
        btle.DefaultDelegate.__init__(self)
        self.bt_mac = bt_mac
        self.name = bt_mac
        self.connected = False

    def logDebug(self, text):
        logging.debug(f'JkBMS {self.name}: {text}')

    def logInfo(self, text):
        logging.info(f'JkBMS {self.name}: {text}')

    def logWarn(self, text):
        logging.warning(f'JkBMS {self.name}: {text}')

    def logError(self, text):
        logging.error(f'JkBMS {self.name}: {text}')

    def initialize(self):
        self.sendCommand(COMMAND_REQ_DEVICE_INFO)
        self.sendCommand(COMMAND_REQ_EXTENDED_RECORD)


    def connect(self):
        if self.connected:
            return

        self.incomingData = bytearray()
        self.device = btle.Peripheral(None)
        self.device.withDelegate(self)
        attempts = 0
        conn = False

        while not conn:
            attempts += 1
            if attempts > 2:
                self.logError(f'cannot connect to JK BMS at {self.bt_mac}')
                exit()
            try:
                self.device.connect(self.bt_mac)
                conn = True
            except Exception as err:
                self.logError(f'connection failed to {self.bt_mac}, re-try')
                print(f"Unexpected {err=}, {type(err)=}")
                time.sleep(1)
                continue

JK_BMS_MAC3 = "C8:47:8C:E4:57:FB"
jkbms3 = jkbms.JkBMS(JK_BMS_MAC3)
jkbms3.initialize()