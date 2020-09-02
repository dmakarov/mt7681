#!/usr/bin/env python

import argparse
import binascii
import functools
import json
import select
import socket
import struct
import time

Cmnd_STK_GET_PARAMETER = b'\x41'
Cmnd_STK_GET_SYNC = b'\x30'
Cmnd_STK_LEAVE_PROGMODE = b'\x51'
Cmnd_STK_LOAD_ADDRESS = b'\x55'
Cmnd_STK_PROG_PAGE = b'\x64'
Cmnd_STK_READ_PAGE = b'\x74'
Cmnd_STK_READ_SIGN = b'\x75'
Parm_STK_SW_MAJOR = b'\x81'
Parm_STK_SW_MINOR = b'\x82'
Resp_STK_INSYNC = b'\x14'
Resp_STK_OK = b'\x10'
Sync_CRC_EOP = b'\x20'


class SerialLine:

    def __init__(self, conf):
        self.conf = conf
        self.params = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((conf['device_address'], conf['slport']))

    def clean(self):
        data = b''
        for it in range(10):
            rlist, _, _ = select.select([self.sock], [], [], 0.001)
            if len(rlist) > 0:
                r = self.sock.recv(1024)
                data += r
        print('Cleaned serial line', data.hex())

    def sync(self):
        packet = b''.join([Cmnd_STK_GET_SYNC, Sync_CRC_EOP])
        reply = b''
        for it in range(10):
            self.sock.sendall(packet)
            print('Sent packet', packet.hex())
            rlist, _, _ = select.select([self.sock], [], [], 0.1)
            if len(rlist) > 0:
                r = self.sock.recv(1)
                reply += r
                if r == Resp_STK_INSYNC:
                    r = self.sock.recv(1)
                    reply += r
                    print('Synced with the bootloader', reply.hex())
                    return True
                else:
                    print('Received', reply.hex())
        print('Unable to sync with bootloader', reply.hex())
        return False

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
                    #print('Success', action, reply.hex())
                    return True
            print('Failure', action, reply.hex())
            return False
        print('Timeout', action)
        return False

    def get_params(self):
        for v in [Parm_STK_SW_MAJOR, Parm_STK_SW_MINOR]:
            packet = b''.join([Cmnd_STK_GET_PARAMETER, v, Sync_CRC_EOP])
            reply = b''
            self.sock.sendall(packet)
            print('Sent packet', packet.hex())
            rlist, _, _ = select.select([self.sock], [], [], 0.1)
            if len(rlist) > 0:
                r = self.sock.recv(1)
                reply += r
                if r == Resp_STK_INSYNC:
                    r = self.sock.recv(2)
                    reply += r
                    print('Got parameter', v.hex(), reply.hex())
                    self.params[v] = reply[1]
                    continue
                print('Failed getting parameter', v.hex(), reply.hex())
                return False
            print('Timeout getting parameter', v.hex())
            return False
        return True

    def get_signature(self):
        packet = b''.join([Cmnd_STK_READ_SIGN, Sync_CRC_EOP])
        reply = b''
        self.sock.sendall(packet)
        print('Sent packet', packet.hex())
        rlist, _, _ = select.select([self.sock], [], [], 0.1)
        if len(rlist) > 0:
            r = self.sock.recv(1)
            reply += r
            if r == Resp_STK_INSYNC:
                r = self.sock.recv(4)
                reply += r
                if reply[4] == Resp_STK_OK[0]:
                    print('Read signature', reply.hex())
                    return reply[1:4]
            print('Failed reading signature', reply.hex())
            return None
        print('Timeout reading signature')
        return None
    def tx(self, command, action):
        packet = b''.join([command, Sync_CRC_EOP])
        self.sock.sendall(packet)
        print('Sent packet', packet.hex())
        return self.ack(action)

    def upload(self, chunks):
        pgsz = self.conf['page_size']
        size = bytes([0xff & (pgsz >> 8), 0xff & pgsz])
        for c in chunks:
            if c.size == 0:
                continue
            addr = c.begin
            index = 0
            while index < len(c.data):
                ab = bytes([0xff & addr, 0xff & (addr >> 8)])
                packet = b''.join([Cmnd_STK_LOAD_ADDRESS, ab, Sync_CRC_EOP])
                self.sock.sendall(packet)
                if not self.ack('setting address {:x}'.format(addr)):
                    if self.conf["verbose"] and index > 0:
                        print()
                    return False
                page = c.data[index:index + pgsz]
                if len(page) < pgsz:
                    padding = pgsz - len(page)
                    page += b'\xff' * padding
                packet = b''.join([Cmnd_STK_PROG_PAGE, size, b'\x46', page, Sync_CRC_EOP])
                self.sock.sendall(packet)
                if not self.ack('programming page'):
                    if self.conf["verbose"] and index > 0:
                        print()
                    return False
                if self.conf["verbose"]:
                    print('{}..'.format(int(100 * index / c.size)), end=' ', flush=True)
                addr += int(pgsz / 2)
                index += pgsz
        if self.conf["verbose"]:
            print()
        return True

    def verify(self, chunks):
        pgsz = self.conf['page_size']
        size = bytes([0xff & (pgsz >> 8), 0xff & pgsz])
        for c in chunks:
            if c.size == 0:
                continue
            addr = c.begin
            index = 0
            while index < len(c.data):
                ab = bytes([0xff & addr, 0xff & (addr >> 8)])
                packet = b''.join([Cmnd_STK_LOAD_ADDRESS, ab, Sync_CRC_EOP])
                self.sock.sendall(packet)
                if not self.ack('setting address {0}'.format(addr)):
                    return
                packet = b''.join([Cmnd_STK_READ_PAGE, size, b'\x46', Sync_CRC_EOP])
                self.sock.sendall(packet)
                reply = b''
                data = b''
                rlist, _, _ = select.select([self.sock], [], [], 10)
                if len(rlist) > 0:
                    r = self.sock.recv(1)
                    reply += r
                    if r == Resp_STK_INSYNC:
                        while len(data) < pgsz:
                            r = self.sock.recv(pgsz - len(data))
                            reply += r
                            data += r
                        r = self.sock.recv(1)
                        reply += r
                        if r != Resp_STK_OK:
                            print('Failed reading page', reply.hex())
                            return False
                        page = c.data[index:index + pgsz]
                        if len(page) < pgsz:
                            padding = pgsz - len(page)
                            page += b'\xff' * padding
                        if data != page:
                            print('Data mismatch')
                            return False
                else:
                    print('Timeout reading page')
                    return False
                addr += int(pgsz / 2)
                index += pgsz
        return True

    def run(self, chunks):
        # all of this must run in less than 0.5 second, for uploading large sketches it's a challenge
        self.clean()
        time.sleep(0.4)
        if not self.sync():
            return
        if self.conf['params']:
            if not self.get_params():
                return
        if self.conf['signature']:
            sign = self.get_signature()
            if sign is None:
                return
        if not self.upload(chunks):
            return
        if self.conf['verify']:
            self.verify(chunks)
        self.tx(Cmnd_STK_LEAVE_PROGMODE, 'leaving program mode')

    def close(self):
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
