import sys
import re
import logging

from .sessions import get_session_by_id, get_sessions_for_hash, delete_session
from .games import get_game_by_name, delete_game

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

# We accept a full channel URL or a gckey.
pat_channel = re.compile('^(?:https://discord.com/channels/)?([0-9]+)[/-]([0-9]+)$')

def cmd_addchannel(args, app):
    match = pat_channel.match(args.channelurl)
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

def cmd_delchannel(args, app):
    match = pat_channel.match(args.channelurl)
    if not match:
        print('argument must be a channel URL: https://discord.com/channels/X/Y')
        return
    gid = match.group(1)
    chanid = match.group(2)
    gckey = gid+'-'+chanid

    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM channels WHERE gckey = ?', (gckey,))
    if not res.fetchone():
        print('channel is not enabled')
        return

    curs.execute('DELETE FROM channels WHERE gckey = ?', (gckey,))    
    print('deleted channel')

def cmd_delsession(args, app):
    session = get_session_by_id(app, args.sessionid)
    if session is None:
        print('no such session:', args.sessionid)
        return

    # TODO: There's a tiny race condition here if someone makes a move in the session while we're deleting. Hand this off to the bot and rely on its inflight locking?
    delete_session(app, session.sessid)
    print('deleted session', args.sessionid)

def cmd_delgame(args, app):
    game = get_game_by_name(app, args.game)
    if game is None:
        print('no such game:', args.game)
        return
    ls = get_sessions_for_hash(app, game.hash)
    if ls:
        sessls = [ str(obj.sessid) for obj in ls ]
        print('game has active sessions:', ', '.join(sessls))
        return

    # TODO: There's a tiny race condition here if someone starts a session while we're deleting.
    delete_game(app, game.hash)
    print('deleted game', game.filename)
    
