import sys
import re
import logging

from .sessions import get_session_by_id, delete_session

def cmd_createdb(args, app):
    curs = app.db.cursor()
    res = curs.execute('SELECT name FROM sqlite_master')
    tables = [ tup[0] for tup in res.fetchall() ]
    
    if 'games' in tables:
        print('"games" table exists')
    else:
        print('creating "games" table...')
        curs.execute('CREATE TABLE games(hash unique, filename, url, format)')

    if 'sessions' in tables:
        print('"sessions" table exists')
    else:
        print('creating "sessions" table...')
        curs.execute('CREATE TABLE sessions(sessid unique, gid, hash, movecount, lastupdate)')

    if 'channels' in tables:
        print('"channels" table exists')
    else:
        print('creating "channels" table...')
        curs.execute('CREATE TABLE channels(gckey unique, gid, chanid, sessid)')

def cmd_cmdinstall(args, app):
    app.cmdsync = True
    bottoken = app.config['DEFAULT']['BotToken']
    app.run(bottoken)
    print('slash commands installed')

def cmd_addchannel(args, app):
    pat = re.compile('^https://discord.com/channels/([0-9]+)/([0-9]+)$')
    match = pat.match(args.channelurl)
    if not match:
        print('argument must be a channel URL: https://discord.com/channels/X/Y')
        return
    gid = match.group(1)
    chanid = match.group(2)
    gckey = gid+'-'+chanid

    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gckey = ?', (gckey,))
    if res.fetchone():
        print('channel is already enabled')
        return

    tup = (gckey, gid, chanid, None)
    curs.execute('INSERT INTO channels (gckey, gid, chanid, sessid) VALUES (?, ?, ?, ?)', tup)
    print('enabled channel')
    
def cmd_delsession(args, app):
    session = get_session_by_id(app, args.sessionid)
    if session is None:
        print('no such session:', args.sessionid)
        return

    delete_session(app, session.sessid)
    print('deleted session')
