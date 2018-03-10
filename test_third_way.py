from datetime import datetime

# 2014-07-09T03:55:48.77
m = datetime.strptime('2014-07-09T03:55:48.77'.split('.')[0], '%Y-%m-%dT%H:%M:%S')
print(datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))