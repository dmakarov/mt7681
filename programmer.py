#!/usr/bin/env python

import argparse
import binascii
import functools
import json
import select
import socket
import struct
import time

# **** ATMEL AVR - A P P L I C A T I O N   N O T E  ************************
# *
# * Title:              AVR061 - STK500 Communication Protocol
# * Filename:           command.h
# * Version:            1.0
# * Last updated:       09.09.2002
# *
# * Support E-mail:     avr@atmel.com
# *
# **************************************************************************

#  *****************[ STK Message constants ]***************************

STK_SIGN_ON_MESSAGE = b'AVR STK'   # Sign on string for Cmnd_STK_GET_SIGN_ON

#  *****************[ STK Response constants ]***************************

Resp_STK_OK = b'\x10'
Resp_STK_FAILED = b'\x11'
Resp_STK_UNKNOWN = b'\x12'
Resp_STK_NODEVICE = b'\x13'
Resp_STK_INSYNC = b'\x14'
Resp_STK_NOSYNC = b'\x15'

Resp_ADC_CHANNEL_ERROR = b'\x16'
Resp_ADC_MEASURE_OK = b'\x17'
Resp_PWM_CHANNEL_ERROR = b'\x18'
Resp_PWM_ADJUST_OK = b'\x19'

# *****************[ STK Special constants ]***************************

Sync_CRC_EOP = b'\x20'  # 'SPACE'

# *****************[ STK Command constants ]***************************

Cmnd_STK_GET_SYNC = b'\x30'
Cmnd_STK_GET_SIGN_ON = b'\x31'
Cmnd_STK_RESET = b'\x32'
Cmnd_STK_SINGLE_CLOCK = b'\x33'
Cmnd_STK_STORE_PARAMETERS = b'\x34'

Cmnd_STK_SET_PARAMETER = b'\x40'
Cmnd_STK_GET_PARAMETER = b'\x41'
Cmnd_STK_SET_DEVICE = b'\x42'
Cmnd_STK_GET_DEVICE = b'\x43'
Cmnd_STK_GET_STATUS = b'\x44'
Cmnd_STK_SET_DEVICE_EXT = b'\x45'

Cmnd_STK_ENTER_PROGMODE = b'\x50'
Cmnd_STK_LEAVE_PROGMODE = b'\x51'
Cmnd_STK_CHIP_ERASE = b'\x52'
Cmnd_STK_CHECK_AUTOINC = b'\x53'
Cmnd_STK_CHECK_DEVICE = b'\x54'
Cmnd_STK_LOAD_ADDRESS = b'\x55'
Cmnd_STK_UNIVERSAL = b'\x56'

Cmnd_STK_PROG_FLASH = b'\x60'
Cmnd_STK_PROG_DATA = b'\x61'
Cmnd_STK_PROG_FUSE = b'\x62'
Cmnd_STK_PROG_LOCK = b'\x63'
Cmnd_STK_PROG_PAGE = b'\x64'
Cmnd_STK_PROG_FUSE_EXT = b'\x65'

Cmnd_STK_READ_FLASH = b'\x70'
Cmnd_STK_READ_DATA = b'\x71'
Cmnd_STK_READ_FUSE = b'\x72'
Cmnd_STK_READ_LOCK = b'\x73'
Cmnd_STK_READ_PAGE = b'\x74'
Cmnd_STK_READ_SIGN = b'\x75'
Cmnd_STK_READ_OSCCAL = b'\x76'
Cmnd_STK_READ_FUSE_EXT = b'\x77'
Cmnd_STK_READ_OSCCAL_EXT = b'\x78'

# *****************[ STK Parameter constants ]***************************

Parm_STK_HW_VER = b'\x80'  # - R
Parm_STK_SW_MAJOR = b'\x81'  # - R
Parm_STK_SW_MINOR = b'\x82'  # - R
Parm_STK_LEDS = b'\x83'  # - R/W
Parm_STK_VTARGET = b'\x84'  # - R/W
Parm_STK_VADJUST = b'\x85'  # - R/W
Parm_STK_OSC_PSCALE = b'\x86'  # - R/W
Parm_STK_OSC_CMATCH = b'\x87'  # - R/W
Parm_STK_RESET_DURATION = b'\x88'  # - R/W
Parm_STK_SCK_DURATION = b'\x89'  # - R/W

Parm_STK_BUFSIZEL = b'\x90'  # - R/W, Range {0..255}
Parm_STK_BUFSIZEH = b'\x91'  # - R/W, Range {0..255}
Parm_STK_DEVICE = b'\x92'  # - R/W, Range {0..255}
Parm_STK_PROGMODE = b'\x93'  # - 'P' or 'S'
Parm_STK_PARAMODE = b'\x94'  # - TRUE or FALSE
Parm_STK_POLLING = b'\x95'  # - TRUE or FALSE
Parm_STK_SELFTIMED = b'\x96'  # - TRUE or FALSE

# *****************[ STK status bit definitions ]***************************

Stat_STK_INSYNC = b'\x01'  # INSYNC status bit, '1' - INSYNC
Stat_STK_PROGMODE = b'\x02'  # Programming mode,  '1' - PROGMODE
Stat_STK_STANDALONE = b'\x04'  # Standalone mode,   '1' - SM mode
Stat_STK_RESET = b'\x08'  # RESET button,      '1' - Pushed
Stat_STK_PROGRAM = b'\x10'  # Program button, '   1' - Pushed
Stat_STK_LEDG = b'\x20'  # Green LED status,  '1' - Lit
Stat_STK_LEDR = b'\x40'  # Red LED status,    '1' - Lit
Stat_STK_LEDBLINK = b'\x80'  # LED blink ON/OFF,  '1' - Blink

# *****************************[ End Of COMMAND.H ]**************************


class SerialLine:

    def __init__(self, conf):
        self.params = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((conf['device_address'], conf['slport']))
        self.clean()

    def clean(self):
        data = b''
        for it in range(10):
            rlist, _, _ = select.select([self.sock], [], [], 0.001)
            if len(rlist) > 0:
                r = self.sock.recv(128)
                data += r
        print('Cleaned serial line', data)

    def sync(self):
        packet = b''.join([Cmnd_STK_GET_SYNC, Sync_CRC_EOP])
        reply = b''
        for it in range(10):
            self.sock.sendall(packet)
            print('Sent packet', packet)
            rlist, _, _ = select.select([self.sock], [], [], 0.1)
            if len(rlist) > 0:
                r = self.sock.recv(1)
                reply += r
                if r == Resp_STK_INSYNC:
                    r = self.sock.recv(1)
                    reply += r
                    print('Synced with the bootloader', reply)
                    return
                else:
                    print('Received', reply)
        print('Unable to sync with bootloader', reply)

    def ack(self, action):
        '''
        Returns: True if the string was found, otherwise False
        Description: It waits for the acknowledge string.
        '''
        reply = b''
        rlist, _, _ = select.select([self.sock], [], [], 20)
        if len(rlist) > 0:
            r = self.sock.recv(1)
            reply += r
            if r == Resp_STK_INSYNC:
                r = self.sock.recv(1)
                reply += r
                if r == Resp_STK_OK:
                    print('Success', action, reply)
                    return True
            print('Failure', action, reply)
            return False
        print('Timeout', action)
        return False

    def get_param(self, arg):
        packet = b''.join([Cmnd_STK_GET_PARAMETER, arg, Sync_CRC_EOP])
        reply = b''
        self.sock.sendall(packet)
        print('Sent packet', packet)
        rlist, _, _ = select.select([self.sock], [], [], 0.1)
        if len(rlist) > 0:
            r = self.sock.recv(1)
            reply += r
            if r == Resp_STK_INSYNC:
                r = self.sock.recv(2)
                reply += r
                print('Got parameter', arg, reply)
                return reply[1]
            print('Failed to get parameter', arg, reply)
            return None
        print('Timeout getting parameter', arg)
        return None

    def set_device(self, devicecode):
        revision = b'\x00'
        progtype = b'\x00'
        parmode = b'\x01'
        polling = b'\x01'
        selftimed = b'\x01'
        pagesizehigh = b'\x00'
        pagesizelow = b'\x80'
        packet = b''.join([Cmnd_STK_SET_DEVICE,
                           devicecode,
                           revision,
                           progtype,
                           parmode,
                           polling,
                           selftimed,
                           b'\x01',
                           b'\x03',
                           b'\xff',
                           b'\xff',
                           b'\xff',
                           b'\xff',
                           pagesizehigh,
                           pagesizelow,
                           b'\x04',
                           b'\x00',
                           b'\x00',
                           b'\x00',
                           b'\x80',
                           b'\x00',
                           Sync_CRC_EOP])
        self.sock.sendall(packet)
        print('Sent packet', packet)
        return self.ack('setting the device')

    def set_device_extended(self):
        packet = b''.join([Cmnd_STK_SET_DEVICE_EXT,
                           b'\x05',
                           b'\x04',
                           b'\xd7',
                           b'\xc2',
                           b'\x00',
                           Sync_CRC_EOP])
        self.sock.sendall(packet)
        print('Sent packet', packet)
        return self.ack('setting the extended device')

    def get_signature(self):
        packet = b''.join([Cmnd_STK_READ_SIGN, Sync_CRC_EOP])
        reply = b''
        self.sock.sendall(packet)
        print('Sent packet', packet)
        rlist, _, _ = select.select([self.sock], [], [], 0.1)
        if len(rlist) > 0:
            r = self.sock.recv(1)
            reply += r
            if r == Resp_STK_INSYNC:
                r = self.sock.recv(4)
                reply += r
                if reply[4] == Resp_STK_OK[0]:
                    print('Read signature', reply)
                    return reply[1:4]
            print('Failed reading signature', reply)
            return None
        print('Timeout reading signature')
        return None

    def tx(self, command, action):
        packet = b''.join([command, Sync_CRC_EOP])
        self.sock.sendall(packet)
        print('Sent packet', packet)
        return self.ack(action)

    def upload(self, chunks):
        for c in chunks:
            if c.size == 0:
                continue
            addr = c.begin
            index = 0
            pgsz = 0x80
            while index < len(c.data):
                ab = bytes([0xff & addr, 0xff & (addr >> 8)])
                packet = b''.join([Cmnd_STK_LOAD_ADDRESS, ab, Sync_CRC_EOP])
                self.sock.sendall(packet)
                print('Sent packet', packet)
                if not self.ack('setting address {0}'.format(addr)):
                    return False
                block = c.data[index:index + pgsz]
                if len(block) < pgsz:
                    padding = pgsz - len(block)
                    block += b'\xff' * padding
                ps = bytes([0xff & (pgsz >> 8), 0xff & pgsz])
                packet = b''.join([Cmnd_STK_PROG_PAGE, ps, b'\x46', block, Sync_CRC_EOP])
                self.sock.sendall(packet)
                print('Sent packet', packet)
                if not self.ack('programming page'):
                    return False
                addr += int(pgsz / 2)
                index += pgsz
        return True

    def verify(self, chunks):
        for c in chunks:
            if c.size == 0:
                continue
            addr = c.begin
            index = 0
            pgsz = 0x80
            while index < len(c.data):
                ab = bytes([0xff & addr, 0xff & (addr >> 8)])
                packet = b''.join([Cmnd_STK_LOAD_ADDRESS, ab, Sync_CRC_EOP])
                self.sock.sendall(packet)
                print('Sent packet', packet)
                if not self.ack('setting address {0}'.format(addr)):
                    return
                block = c.data[index:index + pgsz]
                if len(block) < pgsz:
                    padding = pgsz - len(block)
                    block += b'\xff' * padding
                ps = bytes([0xff & (pgsz >> 8), 0xff & pgsz])
                packet = b''.join([Cmnd_STK_READ_PAGE, ps, b'\x46', Sync_CRC_EOP])
                self.sock.sendall(packet)
                print('Sent packet', packet)
                reply = b''
                data = b''
                rlist, _, _ = select.select([self.sock], [], [], 10)
                if len(rlist) > 0:
                    r = self.sock.recv(1)
                    reply += r
                    if r == Resp_STK_INSYNC:
                        while len(data) < pgsz:
                            r = self.sock.recv(pgsz - len(data))
                            print('Received', len(r), 'bytes of page')
                            reply += r
                            data += r
                        r = self.sock.recv(1)
                        reply += r
                        if r != Resp_STK_OK:
                            print('Failed reading program', reply)
                            return
                        if data != block:
                            print('Data mismatch')
                            return
                        print('Success reading program', reply)
                else:
                    print('Timeout reading program')
                    return
                addr += int(pgsz / 2)
                index += pgsz

    def run(self, chunks):
        time.sleep(0.4)
        self.sync()
        self.sync()
        self.clean()
        for v in [Parm_STK_HW_VER, Parm_STK_SW_MAJOR, Parm_STK_SW_MINOR, b'\x98', Parm_STK_VTARGET, Parm_STK_VADJUST, Parm_STK_OSC_PSCALE, Parm_STK_OSC_CMATCH, Parm_STK_SCK_DURATION]:
            p = self.get_param(v)
            if p is None:
                break
            self.params[v] = p
        if not self.set_device(b'\x86'):
            return
        if not self.set_device_extended():
            return
        if not self.tx(Cmnd_STK_ENTER_PROGMODE, 'entering program mode'):
            return
        sign = self.get_signature()
        if sign is None:
            self.tx(Cmnd_STK_LEAVE_PROGMODE, 'leaving program mode')
            return
        if not self.upload(chunks):
            self.tx(Cmnd_STK_LEAVE_PROGMODE, 'leaving program mode')
            return
        self.verify(chunks)
        self.tx(Cmnd_STK_LEAVE_PROGMODE, 'leaving program mode')

    def close(self):
        self.clean()
        self.sock.close()


class ATLine:
    '''
    +++
    AT+GPIO0=1
    OK
    AT+GPIO0=0
    OK
    AT+EXITAT
    exit AT mode
    '''

    def __init__(self, conf):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((conf['device_address'], conf['atport']))

    def reset(self):
        self.sock.sendall(b'+++')
        print('sent +++')
        self.sock.sendall(b'AT+GPIO0=0')
        r = self.sock.recv(4)
        print('sent AT+GPIO0=0\nrecv', r)
        self.sock.sendall(b'AT+GPIO0=1')
        r = self.sock.recv(4)
        print('sent AT+GPIO0=1\nrecv', r)

    def close(self):
        self.sock.sendall(b'AT+GPIO0=0')
        r = self.sock.recv(4)
        print('sent AT+GPIO0=0\nrecv', r)
        self.sock.sendall(b'AT+GPIO0=?')
        r = self.sock.recv(8)
        print('sent AT+GPIO0=?\nrecv', r)
        self.sock.sendall(b'AT+EXITAT')
        r = self.sock.recv(14)
        print('sent AT+EXITAT\nrecv', r)
        self.sock.close()


class Data:
    '''
    Class containing the data from non-contiguous memory allocations
    '''

    def __init__(self, begin, data):
        self.begin = begin
        self.data = data
        self.size = len(data)

    def __str__(self):
        return 'begin {0}, count {1}, data {2}'.format(self.begin, self.size, self.data)


def parse_line(line):
    '''
    Parameters:  line: a line to parse
    Returns:     The size, address, type of data, data block, and line checksum.
                 True if the checksum is correct, otherwise False.
    Description: parses a line from the .hex file.
    '''
    size = int(line[1:3], 16)
    address = int(line[3:7], 16)
    ty = int(line[7:9], 16)
    pos = 9 + size * 2
    data = binascii.a2b_hex(line[9:pos])
    checksum = int(line[pos:], 16)
    # checking if checksum is correct
    sum = size + (address >> 8) + (address & 0xFF) + ty
    sum += functools.reduce((lambda x, y: int(x) + int(y)), data) if data else 0
    ok = (~(sum & 0xFF) + 1) & 0xFF == checksum
    return (size, address, ty, data, checksum, ok)


def read_hex_file(path):
    '''
    Parameters:  path: The path to the .hex file to read
    Returns:     a list of chunks if the reading was successful, otherwise None.
    Description: reads a .hex file and stores the data in memory.
    '''
    try:
        file = open(path, 'r')
    except IOError:
        print('The hex file could not be opened')
        return None
    line = file.readline()
    if line[0] != ':':
        print('The file is not a valid .hex file')
        file.close()
        return None
    size, address, type, data, checksum, ok = parse_line(line.strip())
    if not ok:
        print('Checksum mismatch in line 1')
        file.close()
        return None
    chunks = []
    chunks.append(Data(address, data))
    # Read the remainder of the hex file
    index = 0
    count = 2
    for line in file:
        size, address, type, data, checksum, ok = parse_line(line.strip())
        if not ok:
            print('Checksum mismatch in line', count)
            file.close()
            return None
        if chunks[index].begin + chunks[index].size == address:
            chunks[index].size += size
            chunks[index].data += data
        else:
            chunks.append(Data(address, data))
            index += 1
        count += 1
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('module', type=str, help='module to upload to an Arduino board')
    ap.add_argument('-c', '--conf', type=str, default='config.json', help='path to the JSON configuration file')
    args = vars(ap.parse_args())
    conf = json.load(open(args['conf']))
    chunks = read_hex_file(args['module'])
    if chunks:
        print('Upload hex file', args['module'], 'to', conf['device_address'])
        sl = SerialLine(conf)
        at = ATLine(conf)
        try:
            at.reset()
            sl.run(chunks)
        except KeyboardInterrupt:
            pass
        at.close()
        sl.close()
    else:
        print('error reading', args['module'])


if __name__ == '__main__':
    main()
