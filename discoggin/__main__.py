import sys
import logging, logging.handlers
import optparse
import configparser

from .client import DiscogClient

popt = optparse.OptionParser(usage='python -m discoggin')

popt.add_option('--cmdsync',
                action='store_true', dest='cmdsync',
                help='upload slash commands to Discord')
popt.add_option('--logstream',
                action='store_true', dest='logstream',
                help='log to stdout rather than the configured file')

(opts, args) = popt.parse_args()

config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']
logfilepath = config['DEFAULT']['LogFile']

if opts.logstream:
    loghandler = logging.StreamHandler(sys.stdout)
else:
    loghandler = logging.handlers.WatchedFileHandler(logfilepath)
logformatter = logging.Formatter('[%(levelname).1s %(asctime)s] %(message)s', datefmt='%b-%d %H:%M:%S')
loghandler.setFormatter(logformatter)

rootlogger = logging.getLogger()
rootlogger.addHandler(loghandler)
rootlogger.setLevel(logging.INFO)
        
client = DiscogClient(config, cmdsync=opts.cmdsync)

client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

