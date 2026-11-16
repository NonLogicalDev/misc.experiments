#!/usr/bin/env python3
"""Publish an existing splat runner's status and stable checkpoints to an activity file."""
import argparse
import json
from pathlib import Path
import time
import run_splat

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('status',type=Path);p.add_argument('activity',type=Path);p.add_argument('output',type=Path);p.add_argument('log',type=Path);a=p.parse_args();observed={}
    while True:
        try:
            state=json.loads(a.status.read_text());observed,ready=run_splat.checkpoints(a.output,observed,state['status']=='complete');run_splat.publish_activity(a.activity,state,a.output,a.log,ready)
            if state['status'] in ('complete','error','cancelled'):break
        except (OSError,ValueError,KeyError,json.JSONDecodeError):pass
        time.sleep(2)
if __name__=='__main__':main()
