import os
import uvicorn
if __name__=='__main__':
    uvicorn.run('stockswatch.app:app',host='0.0.0.0',port=8900,workers=1,log_level='info',proxy_headers=False)
