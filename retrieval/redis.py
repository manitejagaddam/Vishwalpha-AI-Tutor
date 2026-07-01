import redis

r = redis.Redis(
    host='main-social-zany-35066.db.redis.io',
    port=15761,
    decode_responses=True,
    username="default",
    password="FcXa3bLULKaixeEItPMlWAWN22il4m9v",
)

success = r.set('foo', 'bar')
# True

result = r.get('foo')
print(result)
# >>> bar

