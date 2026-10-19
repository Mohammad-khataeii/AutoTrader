from __future__ import annotations

import logging
import os
import re
from typing import Any

from pythonjsonlogger.json import JsonFormatter


class RedactingJsonFormatter(JsonFormatter):
    def process_log_record(self,log_record:dict[str,Any])->dict[str,Any]:
        secrets=[v for k,v in os.environ.items() if v and len(v)>5 and any(s in k.upper() for s in ('PASSWORD','API_KEY','BOT_TOKEN'))]
        def clean(value:Any,key:str='')->Any:
            if any(part in key.lower() for part in ('password','api_key','authorization','bot_token')):
                return '[redacted]'
            if isinstance(value,dict):
                return {k:clean(v,k) for k,v in value.items()}
            if isinstance(value,list):
                return [clean(v) for v in value]
            if isinstance(value,str):
                for secret in secrets:
                    value=value.replace(secret,'[redacted]')
                value=re.sub(r'(?i)(Basic|Bearer)\s+[A-Za-z0-9+/=_\-.]+',r'\1 [redacted]',value)
                value=re.sub(r'(postgresql(?:\+\w+)?://[^:/\s]+:)[^@\s]+@',r'\1[redacted]@',value)
            return value
        return dict(clean(log_record))


def configure_logging()->None:
    handler=logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    root=logging.getLogger()
    root.handlers=[handler]
    root.setLevel(logging.INFO)
