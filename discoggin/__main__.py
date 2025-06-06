import sys
import logging, logging.handlers
import argparse
import configparser

from .client import DiscogClient
from .clifunc import cmd_createdb, cmd_addchannel, cmd_delsession

popt = argparse.ArgumentParser(prog='python -m discoggin')
subopt = popt.add_subparsers(dest='cmd', title='commands')

popt.add_argument('--cmdsync',
                  action='store_true', dest='cmdsync',
                  help='upload slash commands to Discord')
popt.add_argument('--logstream',
                  action='store_true', dest='logstream',
                  help='log to stdout rather than the configured file')

pcmd = subopt.add_parser('createdb', help='create database tables')
pcmd.set_defaults(cmdfunc=cmd_createdb)

pcmd = subopt.add_parser('addchannel', help='add a playing channel')
pcmd.add_argument('channelurl')
pcmd.set_defaults(cmdfunc=cmd_addchannel)

pcmd = subopt.add_parser('delsession', help='delete a session')
pcmd.add_argument('sessionid')
pcmd.set_defaults(cmdfunc=cmd_delsession)

args = popt.parse_args()

config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']
logfilepath = config['DEFAULT']['LogFile']

if args.logstream:
    loghandler = logging.StreamHandler(sys.stdout)
else:
    loghandler = logging.handlers.WatchedFileHandler(logfilepath)
logformatter = logging.Formatter('[%(levelname).1s %(asctime)s] %(message)s', datefmt='%b-%d %H:%M:%S')
loghandler.setFormatter(logformatter)

rootlogger = logging.getLogger()
rootlogger.addHandler(loghandler)
rootlogger.setLevel(logging.INFO)
        
client = DiscogClient(config, cmdsync=args.cmdsync)

if args.cmd:
    args.cmdfunc(args, client)
else:
    client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

