import re
import os, os.path
import urllib.parse
import time
import logging
import hashlib

# Matches empty string, ".", "..", and so on.
pat_alldots = re.compile('^[.]*$')

download_nonce = 1

async def download_game(app, url, chan):
    global download_nonce
    
    logging.info('Downloading %s', url)

    _, _, filename = url.rpartition('/')
    filename = urllib.parse.unquote(filename)
    if pat_alldots.match(filename) or '/' in filename:
        await chan.send('URL does not appear to be a file.')
        return


    download_nonce += 1
    tmpfile = '_tmp_%d_%d_%s' % (time.time(), download_nonce, filename,)
    tmppath = os.path.join(app.gamesdir, tmpfile)
    logging.info('### tmppath %s', tmppath)
    
    async with app.httpsession.get(url) as resp:
        if resp.status != 200:
            await chan.send('Download HTTP error: %s %s: %s' % (resp.status, resp.reason, url))
            return
        totallen = 0
        md5 = hashlib.md5()
        with open(tmppath, 'wb') as outfl:
            async for dat in resp.content.iter_chunked(4096):
                totallen += len(dat)
                outfl.write(dat)
                md5.update(dat)
            dat = None
            hash = md5.hexdigest()

    await chan.send('Downloaded %s (%d bytes)' % (url, totallen,))

    curs = app.db.cursor()
    res = curs.execute('SELECT * FROM games WHERE hash = ?', (hash,))
    tup = res.fetchone()
    if tup:
        await chan.send('Game is already installed!')
        os.remove(tmppath)
        return

    format = detect_format(tmppath)
    if not format:
        await chan.send('Format not recognized!')
        os.remove(tmppath)
        return

def detect_format(path):
    ###
    return 'zcode'
