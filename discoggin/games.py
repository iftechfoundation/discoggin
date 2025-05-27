import logging
import hashlib

async def download_game(app, url, chan):
    logging.info('Downloading %s', url)
    async with app.httpsession.get(url) as resp:
        if resp.status != 200:
            await chan.send('Download HTTP error: %s %s: %s' % (resp.status, resp.reason, url))
            return
        totallen = 0
        md5 = hashlib.md5()
        ### path
        with open('games/tmp', 'wb') as outfl:
            async for dat in resp.content.iter_chunked(4096):
                totallen += len(dat)
                outfl.write(dat)
                md5.update(dat)
            dat = None
            hash = md5.hexdigest()

    print('###', hash, totallen)
    await chan.send('Downloaded %s (%d bytes)' % (url, totallen,))

