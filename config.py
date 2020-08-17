import argparse
import json
from argparse import RawTextHelpFormatter

parser = argparse.ArgumentParser(description=' a Python client for Baidu Pan.', formatter_class=RawTextHelpFormatter)
parser.add_argument('action', choices=['list', 'download'], metavar='action', help='available actions:list, download.\n\
list\t\tlist files and directories in the path.\n\
download\tdownload all files and directories in the path.\n')
parser.add_argument('path', type=str, help='absolute path in Baidu Pan. can be file or directory.')
parser.add_argument('-p', '--local-path', help='specify where the download files will be store.', type=str)
parser.add_argument('-c', '--conf', help='the path of config file.', default='config.json')
parser.add_argument('-s', '--session', help='the path to save session information.', type=str)
parser.add_argument('-u', '--username', help='baidu username. only needed once to generate cookies file.', type=str)
parser.add_argument('-P', '--password', help="baidu password. only needed once to generate cookies file. \
Warning: for security reason, don't save this in config file.", type=str)
parser.add_argument('-a', '--app-id', help='baidu app id. recommended IDs: 498065, 309847, 778750, 250528(official), \
265486, 266719. Some of them can bypass 50M download limitation.', type=int)
parser.add_argument('-o', '--overwrite', action='store_true', help="overwrite existing file when it's presented.")
parser.add_argument('-l', '--log-file', help='specify where to save log.', type=str)
args = parser.parse_args()

config = {'session': "session.pkl", 'username': '', 'password': '', 'app_id': 778750,
          'local_path': '.', "overwrite": False, 'log_file': ''}
conf_f = {}
try:
    with open(args.conf) as f:
        conf_f = json.load(f)
except FileNotFoundError:
    pass

for i in (conf_f.items(), vars(args).items()):
    for k, v in i:
        if v:
            config[k] = v
