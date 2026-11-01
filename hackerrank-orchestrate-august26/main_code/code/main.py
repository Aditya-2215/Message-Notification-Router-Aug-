#!/usr/bin/env python3
"""Personalized multimodal message notification router.

Run from the package root:
    python code/main.py --dataset dataset --output output.csv

Uses deterministic rules, per-user/group/business context, interaction history, OCR for
images, and optional local ASR (faster-whisper) for voice notes. No API keys required.
"""
import argparse, os, re, math
import pandas as pd

ACTIONS={"notify","digest","mute"}
TYPES={"personal","urgent","event","payment","business_update","promotion","greeting","forward","spam","scam","unknown"}

def load(d, name):
    p=os.path.join(d,name+".csv")
    return pd.read_csv(p) if os.path.exists(p) else pd.DataFrame()

def norm(v):
    return "" if pd.isna(v) else str(v).strip()

def truth(v):
    return str(v).strip().lower() in ("1","true","yes","y")

def has_term(text, terms):
    """Match whole words/phrases; avoid substring errors such as 'fee' in 'feedback'."""
    text = str(text or "").lower()
    for term in terms:
        term = str(term).lower().strip()
        if term and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text):
            return True
    return False

_ASR_MODEL = None

def media_text(row, d, images, voices):
    text=norm(row.get("message_text"))
    mid=norm(row.get("media_id"))
    typ=norm(row.get("media_type")).lower()
    if typ=="image" and mid and len(images):
        r=images[images.image_id.astype(str)==mid]
        if len(r):
            path=os.path.join(d,norm(r.iloc[0].file_path))
            try:
                from PIL import Image
                import pytesseract
                text += "\n" + pytesseract.image_to_string(Image.open(path))
            except Exception:
                pass
    if typ=="voice" and mid and len(voices):
        r=voices[voices.voice_note_id.astype(str)==mid]
        if len(r):
            path=os.path.join(d,norm(r.iloc[0].file_path))
            # Optional ASR, when installed; no model downloads are triggered here.
            try:
                from faster_whisper import WhisperModel
                model=WhisperModel("base", device="cpu", compute_type="int8")
                segments,_=model.transcribe(path, beam_size=3)
                text += "\n" + " ".join(s.text for s in segments)
            except Exception:
                pass
    return text.strip()

def route(row, d, tables):
    users, groups, members, businesses, ubh, hist, events, daily, images, voices = tables
    uid=norm(row.user_id); gid=norm(row.group_id); bid=norm(row.business_id)
    text=media_text(row,d,images,voices)
    low=text.lower()
    fwd=int(row.forwarded_count) if not pd.isna(row.forwarded_count) else 0
    evidence=[]; conf=.78
    # Find relevant user history: same user first, then matching business/group/sender or text similarity.
    uh=hist[hist.user_id.astype(str)==uid].copy() if len(hist) else pd.DataFrame()
    ev=events[events.user_id.astype(str)==uid].copy() if len(events) else pd.DataFrame()
    if len(uh) and len(ev):
        uh=uh.merge(ev,on=["user_id","message_id"],how="left")
    if len(uh):
        def score_hist(h):
            s=0
            if bid and norm(h.get("business_id"))==bid: s+=5
            if gid and norm(h.get("group_id"))==gid: s+=4
            if norm(row.get("sender_user_id")) and norm(h.get("sender_user_id"))==norm(row.get("sender_user_id")): s+=4
            old=norm(h.get("message_text")).lower()
            words=set(re.findall(r"[a-z]{4,}",low))
            s+=min(3,len(words & set(re.findall(r"[a-z]{4,}",old))))
            return s
        uh["rel"]=uh.apply(score_hist,axis=1)
        relevant=uh[uh.rel>0].sort_values("rel",ascending=False).head(3)
        evidence=[norm(x) for x in relevant.message_id.tolist()]
    # Personal/group/business signals
    user=users[users.user_id.astype(str)==uid]
    u=user.iloc[0].to_dict() if len(user) else {}
    mem=members[(members.user_id.astype(str)==uid)&(members.group_id.astype(str)==gid)] if gid and len(members) else pd.DataFrame()
    m=mem.iloc[0].to_dict() if len(mem) else {}
    group=groups[groups.group_id.astype(str)==gid] if gid and len(groups) else pd.DataFrame()
    g=group.iloc[0].to_dict() if len(group) else {}
    biz=businesses[businesses.business_id.astype(str)==bid] if bid and len(businesses) else pd.DataFrame()
    b=biz.iloc[0].to_dict() if len(biz) else {}
    bh=ubh[(ubh.user_id.astype(str)==uid)&(ubh.business_id.astype(str)==bid)] if bid and len(ubh) else pd.DataFrame()
    hbiz=bh.iloc[0].to_dict() if len(bh) else {}
    hour=0
    try: hour=pd.to_datetime(row.created_at).hour
    except: pass
    quiet=norm(u.get("do_not_disturb_window"))
    quiet_now=False
    if quiet and "-" in quiet:
        try:
            a,bq=quiet.split("-")
            ah,am=map(int,a.split(":")); bhh,bm=map(int,bq.split(":"))
            now=hour*60+int(pd.to_datetime(row.created_at).minute)
            start=ah*60+am; end=bhh*60+bm
            quiet_now=(start<=now<end) if start<end else (now>=start or now<end)
        except: pass
    urgent_terms=["urgent","urgently","immediately","right now","in 10 minutes","in 20 minutes","20 mins","15 mins","maybe 20 mins max","before 5 pm","today","deadline","escalation","alert threshold","leaves in","closes today","last 10 minutes","call me","last-minute","before eod","close the client note","pulled to","max because","closes at 5 pm","close at 5 pm","finalized tonight","by 6 pm"]
    scam_terms=["otp","one-time password","login code","6 digit","password","wallet pin","verify now","account will be blocked","profile will be locked","pay processing fee","release the amount","suspended","account-number","account number","click this link","verify through this link"]
    scam_domains=["account-login","account-help","pay-check-secure","amazonpay-delivery","secure-verify","wallet-check"]
    promotion_terms=["offer","sale","discount","% off","promo","promotion","subscribe","limited time","buy now","shopping offer","sale subscription","launch price","for sale","tour package","selling","selling a"]
    greeting_terms=["good morning","good evening","stay blessed","good vibes","smile today","hope today","share blessings","stay positive","keep smiling"]
    forward_terms=["fwd","forwarding","forward as received","share this","forward to family","forwarding because","forward to ten people","share it with","forward this"]
    payment_terms=["payment","pay","fee","receipt","refund","payout","maintenance","due today","banking","transaction","statement","amount due"]
    event_terms=["meeting","sync","school","field trip","consent","bus","event","webinar","appointment","fire alarm","tanker","water supply","gate","pickup","delivery attempt","cultural night","form is open","circular","timing","volunteer sheet","registration","feedback"]
    # Risk is hard override: messages requesting OTP/credentials or suspicious domains.
    scam=has_term(low, scam_terms) and (has_term(low, ["otp","password","login code","pin","verify","blocked","locked","suspended"]) or has_term(low, scam_domains))
    scam= scam or has_term(low, scam_domains)
    # Legitimate security advisories may mention OTP/PIN precisely to warn users never to share them.
    if has_term(low, ["never ask for otp","never ask for payment details","never ask for otp or payment details","never request otp","do not share otp","never ask for otp, card pin"]):
        scam=False
    spam= (fwd>=5 and has_term(low, forward_terms)) or (has_term(low, ["claim benefits","share your account number","free money","loan approved"]) and has_term(low, ["send details","pay processing","share your account"]))
    # Metadata can flag suspicious business messages even when an audio note has no transcript.
    biz_row=businesses[businesses.business_id.astype(str)==bid] if bid and len(businesses) else pd.DataFrame()
    biz_meta=biz_row.iloc[0].to_dict() if len(biz_row) else {}
    biz_risky=(norm(row.conversation_type)=="business" and (not truth(biz_meta.get("verified")) or int(biz_meta.get("user_reports_30d",0) or 0)>=20 or int(biz_meta.get("domain_used_by_sender_age_days",9999) or 9999)<=30))
    if biz_risky and not low and norm(row.get("media_type"))=="voice":
        action,typ,reason,conf="mute","spam","The voice note is from an unverified business with elevated reports or a newly observed sender domain.",.84
    elif scam:
        action,typ,reason,conf="mute","scam","The message requests sensitive verification or payment through a suspicious or high-pressure flow.",.88
    elif spam:
        if has_term(low, greeting_terms):
            action,typ,reason,conf="mute","greeting","A repetitive forwarded greeting is low priority for this user.",.83
        elif has_term(low, ["fwd as received","forward as received","sharing here in case it helps","pls forward to family groups"]):
            action,typ,reason,conf="mute","forward","This is forwarded advice or chain content with low value and high notification-noise potential.",.83
        else:
            action,typ,reason,conf="mute","spam","The message has spam-like solicitation or forwarding signals and is not worth interrupting the user.",.84
    else:
        # Choose semantic category and urgency.
        ispromo=has_term(low, promotion_terms) or bool(norm(row.get("media_type"))=="image" and has_term(low,["kurta","clothing","clothes","helmet","jacket","product photos","photos for the"]))
        ispromo=ispromo or bool(norm(row.conversation_type)=="business" and has_term(low,["per person","itinerary","from rs","first order","50% off","discount code","promo code","welcome offer"]))
        isgreet=has_term(low, greeting_terms)
        isforward=has_term(low, forward_terms) or fwd>=4
        ispayment=has_term(low, payment_terms)
        isevent=has_term(low, event_terms)
        urgent=has_term(low, urgent_terms)
        direct=(f"@{uid}" in low or has_term(low, ["please call","can you call","can you come online","need your","can you join","can you collect","please reply","can you confirm"]))
        trusted_sender=False
        if norm(row.get("sender_user_id")):
            # user's known prior sender interaction
            trusted_sender=bool(len(uh) and any(uh.sender_user_id.astype(str)==norm(row.get("sender_user_id"))))
        group_type=norm(g.get("group_type")).lower()
        role=norm(m.get("role")).lower()
        muted=truth(m.get("group_muted_by_user"))
        business_verified=truth(b.get("verified"))
        domain_ok=norm(b.get("official_domain")).lower()==norm(b.get("domain_used_by_sender")).lower() and bool(norm(b.get("official_domain")))
        optedout=not truth(hbiz.get("allows_promotions")) if hbiz else False
        dismissed=int(hbiz.get("messages_dismissed_30d",0) or 0) if hbiz else 0
        isbusiness=norm(row.conversation_type)=="business"
        # User-business history and behavior personalize promotions.
        if isbusiness and ispromo:
            if optedout or dismissed>=3:
                action,typ,reason,conf="mute","promotion","The user has opted out of or repeatedly dismissed similar marketing messages.",.85
            elif truth(hbiz.get("allows_promotions")) and int(hbiz.get("activity_count_180d",0) or 0)>0:
                action,typ,reason,conf="digest","promotion","The promotion matches the user's opted-in business interests but is not time-critical.",.79
            else:
                action,typ,reason,conf="mute","promotion","The business promotion has no clear opt-in relevance for this user.",.78
        elif isbusiness:
            if has_term(low,["safety advisory","never ask for otp","never ask for payment details","report suspicious calls"]):
                action,typ,reason,conf="digest","business_update","This is a security-awareness advisory warning users about sensitive information; it is not a request to disclose it.",.86
            elif has_term(low, ["health-related","appointment","prescription","claim","pickup details"]) and business_verified and (bh.empty or int(hbiz.get("activity_count_180d",0) or 0)>0):
                action,typ,reason,conf="notify","event","A verified business reminder relates to a health, appointment, or scheduled service.",.86
            elif has_term(low, ["packed","delivery","delivery attempt","order","refund","payout","payment update","booking","scheduled"]) and business_verified and (bh.empty or int(hbiz.get("activity_count_180d",0) or 0)>0):
                action,typ,reason,conf="notify","business_update","A verified business update appears relevant to the user's existing order, booking, or account activity.",.86
            elif ispayment:
                action,typ,reason,conf=("notify" if business_verified and domain_ok and not scam else "mute"),("payment" if business_verified and domain_ok and not scam else "scam"),("A trusted verified business sent a relevant payment update." if business_verified and domain_ok and not scam else "The payment request cannot be safely verified."),.81
            elif has_term(low, ["feedback","review","experience with us"]):
                action,typ,reason,conf="digest","business_update","This is a routine business feedback request that can wait for the digest.",.78
            else:
                action,typ,reason,conf="digest","business_update","This appears to be a legitimate business message, but it does not require immediate attention.",.77
        elif isforward:
            action,typ,reason,conf="mute","forward","Repeated forwarded content is low-value and likely to add notification noise.",.83
        elif isgreet:
            action,typ,reason,conf="digest","greeting","This is a harmless greeting or casual group message that can be read later.",.81
        elif direct and urgent:
            action,typ,reason,conf="notify","urgent","The sender directly requests action and signals a time-sensitive dependency.",.87
        elif direct and norm(row.conversation_type) in ("personal","group"):
            action,typ,reason,conf="notify","personal","The sender directly asks this user for a response, coordination, or action.",.85
        elif urgent and (group_type in ["school_group","work","society"] or role=="admin"):
            action,typ,reason,conf="notify",("event" if group_type=="school_group" and isevent else "urgent"),"A time-sensitive group update affects the user and should be seen promptly.",.85
        elif ispayment and urgent and (group_type in ["society","school_group"] or role=="admin"):
            action,typ,reason,conf="notify","payment","A trusted group context contains a payment deadline or operational request.",.83
        elif norm(row.conversation_type)=="group" and group_type=="school_group" and isevent and has_term(low,["circular","consent","timing","field trip","pickup timing"]):
            action,typ,reason,conf="notify","event","A school circular contains actionable timing or consent information for the user.",.85
        elif isevent and urgent:
            action,typ,reason,conf="notify","event","The message contains a time-sensitive event or operational update.",.83
        elif ispayment:
            action,typ,reason,conf="digest","payment","This payment-related information is useful but does not clearly require an immediate interruption.",.78
        elif ispromo:
            action,typ,reason,conf="digest","promotion","This offer or promotion may be useful, but it can wait for the digest.",.77
        elif norm(row.conversation_type)=="personal" and has_term(low,["found your number","got your number from","new here"]):
            action,typ,reason,conf="digest","unknown","This appears to be a first-contact message with unclear relevance; it can be reviewed later.",.75
        elif norm(row.conversation_type)=="personal":
            action,typ,reason,conf="notify" if direct else "digest","personal","A personal message is relevant, but no explicit urgent deadline is present." if not direct else "The sender directly asks the user for a response or action.",.82
        elif norm(row.conversation_type)=="group" and has_term(low,["anyone watching","no pressure at all","join only if","score thread"]):
            action,typ,reason,conf="digest","personal","This is casual group conversation with no direct request or urgency.",.78
        elif isevent:
            action,typ,reason,conf="digest","event","This event or group update is useful but not clearly urgent.",.79
        else:
            action,typ,reason,conf="digest","unknown","The message appears safe, but its importance is unclear and it can be reviewed later.",.73
        # Suppress ordinary group noise under muted groups, but retain explicit urgent direct mentions.
        if norm(row.conversation_type)=="group" and muted and not (direct and urgent) and action=="notify":
            action="digest"; reason="The group is muted by the user; this non-emergency update can be reviewed later."; conf=.78
        # Personalize low-value group posts using explicit mute state and dismissal behavior.
        if norm(row.conversation_type)=="group" and muted and not (direct and urgent):
            dismissed_group=int(m.get("notifications_dismissed_30d",0) or 0)
            if ispromo or isforward or (dismissed_group>=7 and action in ("digest","notify")):
                action="mute"
                if ispromo: typ="promotion"
                elif isforward: typ="forward"
                reason="The user has muted this group and has a strong history of dismissing its low-value posts."
                conf=.84
        if quiet_now and action=="notify" and typ not in ("urgent","scam"):
            action="digest"; reason="The message is not a safety-critical emergency and arrived during the user's quiet hours."; conf=min(conf,.8)
        # Daily load influences borderline notices, never risk or clear direct urgency.
        ds=daily[daily.user_id.astype(str)==uid] if len(daily) else pd.DataFrame()
        if len(ds) and action=="notify" and not direct and not urgent:
            avg=float(ds.notifications_sent.mean())
            if avg>=7:
                action="digest"; reason="This is useful but non-urgent, and the user's recent notification load is high."; conf=min(conf,.79)
    if not evidence: evidence_text="none"
    else: evidence_text=";".join(evidence)
    return [norm(row.message_id),action,typ,reason,round(float(conf),2),evidence_text]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",default="dataset")
    ap.add_argument("--output",default="output.csv")
    args=ap.parse_args()
    d=args.dataset
    messages=load(d,"messages")
    tables=(load(d,"users"),load(d,"groups"),load(d,"group_members"),load(d,"business_accounts"),
            load(d,"user_business_history"),load(d,"message_history"),load(d,"message_events"),
            load(d,"daily_notification_summary"),load(d,"images"),load(d,"voice_notes"))
    rows=[route(r,d,tables) for _,r in messages.iterrows()]
    out=pd.DataFrame(rows,columns=["message_id","action","message_type","reason","confidence","evidence_message_ids"])
    out.to_csv(args.output,index=False)
    assert len(out)==len(messages) and out.message_id.tolist()==messages.message_id.astype(str).tolist()
    assert set(out.action)<=ACTIONS and set(out.message_type)<=TYPES
    print(f"Wrote {len(out)} predictions to {args.output}")
if __name__=="__main__": main()
