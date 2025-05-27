import sys
import logging, logging.handlers
import argparse
import configparser

from .client import DiscogClient

popt = argparse.ArgumentParser(prog='python -m discoggin')

popt.add_argument('--cmdsync',
                  action='store_true', dest='cmdsync',
                  help='upload slash commands to Discord')
popt.add_argument('--logstream',
                  action='store_true', dest='logstream',
                  help='log to stdout rather than the configured file')

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

#client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

