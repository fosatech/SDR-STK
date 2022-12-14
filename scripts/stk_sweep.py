import socket
import select
import sys
import struct
import threading
import time
import argparse
import subprocess

epilog_example = """Examples: [[ python stk_sweep.py -o "-f 420M:500M:5k -g 1 -i 2s" ]] or  [[ rtl_power -f 420M:500M:5k -g 1 -i 1s | python stk_sweep.py -p ]]"""



class Forward:
    def __init__(self):
        self.forward = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def start(self, host, port):
        try:
            self.forward.connect((host, port))
            return self.forward
        except Exception as e:
            print(e)
            return False

class Server:

    def __init__(self):

        self.SET_FREQUENCY = 0x01

        self.top_Freq = {
            "freq" : 0,
            "dBm" : "0"
        }


        self.buffer_size = 4096
        self.delay = 0.0001

        self.args = self._build_parser()

        self.power_args = ['rtl_power']
        self.power_args += self.args.options.split(' ')

        self._build_rtl_tcp()

        self.forward_ip = self.args.client_ip
        self.forward_port = self.args.client_port

        self.input_list = []
        self.channel = {}

        self.forward = None

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.args.serv_ip, self.args.serv_port))
        self.server.listen(200)


    def main(self):

        """Starts the main proxy server."""

        self.input_list.append(self.server)
        case_init = True

        while 1:

            time.sleep(self.delay)
            ss = select.select
            inputready, outputready, exceptready = ss(self.input_list, [], [])

            for self.s in inputready:
                if self.s == self.server:
                    print("accept")
                    self._on_accept()

                    get_data = threading.Thread(target=self._inject, name="Inject")
                    get_data.start()


                    break

                self.data = self.s.recv(self.buffer_size)
                if len(self.data) == 0:
                    self._on_close()
                    break
                else:
                    self._on_recv()


    def kill_all(self):

        self.tcp_process.kill()
        self.power_process.kill()


    def _build_rtl_tcp(self):

        self.tcp_process = subprocess.Popen(['rtl_tcp', '-d', '1', '-a', str(self.args.client_ip), '-p', str(self.args.client_port)], stdout=subprocess.PIPE)


    def _build_parser(self):

        parser = argparse.ArgumentParser(
            prog = 'rtl_sweep',
            description = 'An rtl_power utility that detects dBm peaks and passes the freqency to an rtl_tcp instance.',
            epilog = epilog_example)

        parser.add_argument('-o', dest='options', type=str, default=None,
            help='Input rtl_power options as a string.')
        parser.add_argument('-i', dest='pipe', action='store_true',
            help='No rtl_power options, run in pipe mode.')
        parser.add_argument('-s', dest='serv_ip', default='127.0.0.1',
            help='Server IP address (default: localhost)')
        parser.add_argument('-p', dest='serv_port', default=1236,
            help='Server Port (default: 1236)')
        parser.add_argument('-c', dest='client_ip', default='127.0.0.1',
            help='Client IP (default: localhost)')
        parser.add_argument('-a', dest='client_port', default=1234,
            help='Client Port (default: 1234)')
        parser.add_argument('-d', dest='db_limit', default=0,
            help='Set dBm peak detect limit (default: 0dBm)')
        parser.add_argument('-v', dest='logging', action='store_const',
            const=True, default=False,
            help='Enable freqency and dBm logging in the console')

        return parser.parse_args()


    def _inject(self):

        """This function contains all of the logic for selecting peaks from the rtl_power input."""

        self.power_process = subprocess.Popen(self.power_args, stdout=subprocess.PIPE)

        low_freq = 0

        while True:
            output = self.power_process.stdout.readline()
            if self.power_process.poll() is not None:
                break
            if output:

                input = output.decode().split(', ')

                start_freq = input[2]
                step = input[4]
                db = input[6:]

                max_index = db.index(max(db))
                max_value = max(db)
                freq = int(start_freq) + max_index * float(step)

                if float(start_freq) >= low_freq:
                    low_freq = float(start_freq)

                    self._send_command(self.SET_FREQUENCY, int(self.top_Freq["freq"]))

                    if self.args.logging is True:
                        print(self.top_Freq["freq"], self.top_Freq["dBm"])

                    self.top_Freq["dBm"] = str(self.args.db_limit)


                if max_value > self.top_Freq["dBm"] :
                    self.top_Freq["freq"] = freq
                    self.top_Freq["dBm"] = max_value


    def _on_accept(self):

        self.forward = Forward().start(self.forward_ip, self.forward_port)
        clientsock, clientaddr = self.server.accept()
        if self.forward:
            print(clientaddr, "has connected")
            self.input_list.append(clientsock)
            self.input_list.append(self.forward)
            self.channel[clientsock] = self.forward
            self.channel[self.forward] = clientsock
        else:
            print("Can't establish connection with remote server.",)
            print("Closing connection with client side", clientaddr)
            clientsock.close()


    def _on_close(self):

        print(self.s.getpeername(), "has disconnected")

        #remove objects from input_list
        self.input_list.remove(self.s)
        self.input_list.remove(self.channel[self.s])
        out = self.channel[self.s]

        # close the connection with client
        self.channel[out].close()  # equivalent to do self.s.close()

        # close the connection with remote server
        self.channel[self.s].close()

        # delete both objects from channel dict
        del self.channel[out]
        del self.channel[self.s]


    def _on_recv(self):

        self.channel[self.s].send(self.data)
        

    def _send_command(self, command, param):

        cmd = struct.pack(">BI", command, param)
        self.forward.send(cmd)



if __name__ == '__main__':

        # this is the IP:port that the external SDR software will conenct to.
        server = Server()
        try:
            server.main()
        except (Exception, KeyboardInterrupt):
            server.kill_all()
            print("[!] Interrupt - Stopping server")
            sys.exit(1)
