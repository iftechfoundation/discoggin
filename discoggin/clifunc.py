
def cmd_createdb(args, app):
    curs = app.db.cursor()
    res = curs.execute('SELECT name FROM sqlite_master')
    tables = [ tup[0] for tup in res.fetchall() ]
    
    if 'games' in tables:
        print('"games" table exists')
    else:
        print('creating "games" table...')
        curs.execute('CREATE TABLE games(hash unique, filename, url, format)')
