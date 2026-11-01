#!/usr/bin/env python3
import argparse, os, sys
import pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from main import load, route

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset", default="dataset")
    args=ap.parse_args()
    d=args.dataset
    sample=load(d,"sample_messages")
    tables=(load(d,"users"),load(d,"groups"),load(d,"group_members"),load(d,"business_accounts"),
            load(d,"user_business_history"),load(d,"message_history"),load(d,"message_events"),
            load(d,"daily_notification_summary"),load(d,"images"),load(d,"voice_notes"))
    out=pd.DataFrame([route(r,d,tables) for _,r in sample.iterrows()],
        columns=["message_id","action","message_type","reason","confidence","evidence_message_ids"])
    print(f"Sample rows: {len(sample)}")
    print(f"Action agreement: {(out.action == sample.action).mean():.1%}")
    print(f"Message type agreement: {(out.message_type == sample.message_type).mean():.1%}")
    mismatch=sample.loc[(out.action != sample.action)|(out.message_type != sample.message_type),
        ["message_id","action","message_type"]].copy()
    mismatch["pred_action"]=out.loc[mismatch.index,"action"].values
    mismatch["pred_type"]=out.loc[mismatch.index,"message_type"].values
    if len(mismatch):
        print("\nMismatches:")
        print(mismatch.to_string(index=False))
if __name__=="__main__": main()
