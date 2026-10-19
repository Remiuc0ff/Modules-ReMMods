__version__ = (1, 4, 0, 0)

import base64, io, logging, re, requests
from datetime import datetime
from time import gmtime
from typing import List, Optional, Tuple, Union
from PIL import Image, ImageDraw

import telethon
from telethon.tl import functions, types
from telethon.tl.patched import Message

from .. import loader, utils

logger=logging.getLogger(__name__)

class Dick:
    @staticmethod
    def safe_html_parse(text: str):
        if not text: return "", []
        try:
            from telethon.extensions import html
            return html.parse(text)
        except Exception:
            return re.sub(r'<[^>]+>', '', text), []

    @staticmethod
    def is_type(value, *names) -> bool:
        return value is not None and type(value).__name__ in names

    @staticmethod
    def parse_msg_link(arg: str) -> Optional[Tuple[Union[str, int], int]]:
        if not isinstance(arg, str) or not arg:
            return None
        arg = arg.strip()
        m = re.match(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.(?:me|dog))/c/(\d+)(?:/\d+)?/(\d+)(?:/|\?.*)?$", arg)
        if m:
            return int(f"-100{m.group(1)}"), int(m.group(2))
        m = re.match(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.(?:me|dog))/([a-zA-Z0-9_]+)(?:/\d+)?/(\d+)(?:/|\?.*)?$", arg)
        if m:
            domain = m.group(1)
            if domain.lower() not in ("c", "joinchat", "addstickers", "addemoji", "share", "setlanguage", "iv", "proxy", "socks", "bg"):
                return domain, int(m.group(2))
        return None

    @staticmethod
    def tl_json(value):
        if value is None or isinstance(value,(str,float,bool)): return value
        if isinstance(value, int):
            return str(value) if abs(value)>9007199254740991 else value
        if isinstance(value,bytes): return {"_bytes":base64.b64encode(value).decode()}
        if isinstance(value,(list,tuple)): return [Dick.tl_json(item) for item in value]
        if isinstance(value,dict): return {str(key):Dick.tl_json(item) for key,item in value.items()}
        try:
            return Dick.tl_json(value.to_dict())
        except Exception:
            return str(value)

    @staticmethod
    def walk_json(value):
        if isinstance(value,dict):
            yield value
            for child in value.values():
                yield from Dick.walk_json(child)
        elif isinstance(value,list):
            for child in value:
                yield from Dick.walk_json(child)

    @staticmethod
    def data(b: bytes, mime: str) -> str:
        return f"data:{mime};base64,{base64.b64encode(b).decode()}"

    @staticmethod
    def mime(b: bytes, fallback: str="application/octet-stream") -> str:
        if b.startswith(b"\xff\xd8\xff"): return "image/jpeg"
        if b.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
        if b.startswith((b"GIF87a",b"GIF89a")): return "image/gif"
        if b.startswith(b"RIFF") and b[8:12]==b"WEBP": return "image/webp"
        return fallback

    @staticmethod
    async def download(cli, obj) -> Optional[bytes]:
        b=None
        try: b=await cli.download_media(obj,bytes,thumb=-1)
        except Exception: pass
        if not b: b=await cli.download_media(obj,bytes)
        return b or None

    @staticmethod
    async def map_preview(cli, geo, width=640, height=320, zoom=13, scale=1) -> Optional[dict]:
        def field(value, name, default=None):
            return value.get(name,default) if isinstance(value,dict) else getattr(value,name,default)

        width=max(64,min(int(width or 640),1024)); height=max(64,min(int(height or 320),1024))
        zoom=max(13,min(int(zoom or 13),20)); scale=max(1,min(int(scale or 1),3))
        location=types.InputWebFileGeoPointLocation(
            geo_point=types.InputGeoPoint(lat=float(field(geo,"lat")),long=float(field(geo,"long")),accuracy_radius=None),
            access_hash=int(field(geo,"access_hash",0) or 0),w=width,h=height,zoom=zoom,scale=scale)
        part_size=128*1024; max_size=8*1024*1024
        offset=0; expected_size=None; chunks=[]; mime="image/jpeg"
        sender=cli._sender; exported_sender=None
        try:
            while offset<max_size:
                request=functions.upload.GetWebFileRequest(location=location,offset=offset,limit=part_size)
                while True:
                    try:
                        preview=await cli._call(sender,request)
                        break
                    except telethon.errors.FileMigrateError as error:
                        if exported_sender is not None:
                            await cli._return_exported_sender(exported_sender)
                            exported_sender=None
                        exported_sender=await cli._borrow_exported_sender(error.new_dc)
                        sender=exported_sender
                chunk=getattr(preview,"bytes",None) or b""
                if not chunk: break
                if expected_size is None:
                    expected_size=int(getattr(preview,"size",0) or 0)
                    mime=getattr(preview,"mime_type",None) or mime
                chunks.append(chunk)
                offset+=len(chunk)
                if (expected_size and offset>=expected_size) or len(chunk)<part_size: break
        finally:
            if exported_sender is not None: await cli._return_exported_sender(exported_sender)
        b=b"".join(chunks)
        if not b: return None
        return {"url":Dick.data(b,mime),"mime_type":mime,"file_size":len(b),"width":width,"height":height}

    @staticmethod
    async def rich(cli, message: Message) -> Optional[dict]:
        rich=getattr(message,"rich_message",None)
        if not rich: return None
        result=Dick.tl_json(rich); files={}
        objects=list(getattr(rich,"photos",None) or [])+list(getattr(rich,"documents",None) or [])
        for obj in objects:
            object_id=getattr(obj,"id",None)
            if object_id is None: continue
            try:
                b=await Dick.download(cli,obj)
                if not b: continue
                mime=Dick.mime(b,getattr(obj,"mime_type",None) or "image/jpeg")
                attrs=getattr(obj,"attributes",None) or []
                audio=next((a for a in attrs if isinstance(a,types.DocumentAttributeAudio)),None)
                custom_emoji=next((a for a in attrs if isinstance(a,types.DocumentAttributeCustomEmoji)),None)
                dimensions=next((a for a in attrs if hasattr(a,"w") and hasattr(a,"h")),None)
                if not dimensions:
                    dimensions=next((size for size in reversed(getattr(obj,"sizes",None) or [])
                                     if hasattr(size,"w") and hasattr(size,"h")),None)
                files[str(object_id)]={"url":Dick.data(b,mime),"mime_type":mime,
                    "file_size":getattr(obj,"size",None),
                    "file_name":next((getattr(a,"file_name",None) for a in attrs if getattr(a,"file_name",None)),None),
                    "width":getattr(dimensions,"w",None),"height":getattr(dimensions,"h",None),
                    "duration":getattr(audio,"duration",None),"title":getattr(audio,"title",None),
                    "performer":getattr(audio,"performer",None),
                    "text_color":bool(getattr(custom_emoji,"text_color",False))}
            except Exception:
                continue

        map_index=0
        for block in Dick.walk_json(result):
            if block.get("_")!="PageBlockMap": continue
            geo=block.get("geo") or {}
            try:
                width=max(64,min(int(block.get("w") or 640),1024))
                height=max(64,min(int(block.get("h") or 320),1024))
                preview=await Dick.map_preview(cli,geo,width,height,block.get("zoom") or 15)
                if not preview: continue
                file_id=f"map-preview:{map_index}"; map_index+=1
                files[file_id]=preview; block["map_preview_key"]=file_id
            except Exception:
                logger.exception("failed to download rich-message map")
        result["files"]=files
        return result

    @staticmethod
    def color_pack(value) -> List[int]:
        if not value: return []
        colors=getattr(value,"colors",None) or getattr(value,"palette_colors",None) or []
        return [int(color) & 0xffffff for color in colors]

    @staticmethod
    def peer_color(peer, palettes: Optional[dict]) -> Optional[dict]:
        if palettes is None:
            return None
        color=getattr(peer,"color",None)
        if Dick.is_type(color,"PeerColorCollectible"):
            return {"type":"collectible","collectible_id":str(color.collectible_id),
                    "gift_emoji_id":str(color.gift_emoji_id),
                    "background_emoji_id":str(color.background_emoji_id),
                    "accent_color":int(color.accent_color)&0xffffff,
                    "colors":[int(value)&0xffffff for value in (color.colors or [])],
                    "dark_accent_color":None if color.dark_accent_color is None else int(color.dark_accent_color)&0xffffff,
                    "dark_colors":[int(value)&0xffffff for value in (color.dark_colors or [])]}
        if isinstance(color,int):
            result={"type":"preset","color":color}
            if color in palettes: result.update(palettes[color])
            return result
        if Dick.is_type(color,"PeerColor"):
            result={"type":"preset","color":color.color}
            if color.background_emoji_id is not None:
                result["background_emoji_id"]=str(color.background_emoji_id)
            if color.color in palettes: result.update(palettes[color.color])
            return result
        return None

    @staticmethod
    def person(peer, name: str, avatar: Optional[str], palettes: dict, chained: bool=False) -> dict:
        uid=getattr(peer,"id",0); f,l=Dick.split(name)
        result={"id":uid,"first_name":getattr(peer,"first_name","") or f,
                "last_name":getattr(peer,"last_name","") or l,"username":getattr(peer,"username",None),
                "name":False if chained else name,"photo":{"url":avatar} if avatar else {}}
        color=Dick.peer_color(peer,palettes)
        if color: result["peerColor"]=color
        if not chained:
            status=getattr(peer,"emoji_status",None)
            if getattr(status,"document_id",None): result["emoji_status"]=str(status.document_id)
        return result

    @staticmethod
    def u16(value) -> int:
        return len(str(value or "").encode("utf-16-le"))//2

    @staticmethod
    def shift(entities: List[dict], offset: int) -> List[dict]:
        out=[]
        for entity in entities or []:
            item=dict(entity); item["offset"]=int(item.get("offset",0))+offset; out.append(item)
        return out

    @staticmethod
    def preview(text: str="", icon: Optional[str]=None, entities: Optional[List[dict]]=None,
                thumbnail: bool=False, **extra) -> dict:
        result={"text":text,"icon":icon,"entities":entities or [],"thumbnail":thumbnail}
        result.update(extra)
        return result

    @staticmethod
    def flat_text(value) -> str:
        return str(value or "").replace("\r\n"," ").replace("\n"," ").replace("\r"," ")

    @staticmethod
    def extract_rich_text(node) -> Tuple[str,List[dict]]:
        if not node: return "",[]
        if isinstance(node,str): return Dick.flat_text(node),[]
        if isinstance(node,types.TextPlain): return Dick.flat_text(node.text),[]
        if isinstance(node,types.TextEmpty): return "",[]
        if isinstance(node,types.TextCustomEmoji):
            alt=node.alt or " "
            return alt,[{"type":"custom_emoji","offset":0,"length":Dick.u16(alt),"custom_emoji_id":str(node.document_id)}]
        if isinstance(node,types.TextConcat):
            full_t=""; full_e=[]
            for sub in node.texts or []:
                st,se=Dick.extract_rich_text(sub)
                full_e.extend(Dick.shift(se,Dick.u16(full_t)))
                full_t+=st
            return full_t,full_e
        inner=getattr(node,"text",None)
        if inner is not None:
            it,ie=Dick.extract_rich_text(inner)
            u16_l=Dick.u16(it)
            type_map={types.TextBold:"bold",
                      types.TextItalic:"italic",
                      types.TextUnderline:"underline",
                      types.TextStrike:"strikethrough",
                      types.TextFixed:"code",
                      types.TextUrl:"text_link",
                      types.TextSpoiler:"spoiler",
                      types.TextMarked:"spoiler"}
            ent_t=type_map.get(type(node))
            ents=[]
            if ent_t and u16_l>0:
                ent={"type":ent_t,"offset":0,"length":u16_l}
                if isinstance(node,types.TextUrl):
                    ent["url"]=getattr(node,"url","")
                ents.append(ent)
            ents.extend(ie)
            return it,ents
        if hasattr(node,"caption"):
            cap=getattr(node,"caption")
            if cap:
                return Dick.extract_rich_text(getattr(cap,"text",cap))
        return "",[]

    @staticmethod
    def strip_with_entities(t: str, ents: List[dict]) -> Tuple[str,List[dict]]:
        if not t: return "",[]
        l_t=t.lstrip()
        l_diff=Dick.u16(t[:len(t)-len(l_t)])
        cur_t=l_t.rstrip()
        max_l=Dick.u16(cur_t)
        new_ents: List[dict]=[]
        for e in ents:
            off=int(e.get("offset",0))-l_diff
            ln=int(e.get("length",0))
            if off<0:
                ln+=off
                off=0
            if ln>0 and off<max_l:
                ln=min(ln,max_l-off)
                item=dict(e)
                item["offset"]=off
                item["length"]=ln
                new_ents.append(item)
        return cur_t,new_ents

    @staticmethod
    def extract_block_text(b) -> Tuple[str,List[dict]]:
        if not b: return "",[]
        parts_t: List[str]=[]
        parts_e: List[dict]=[]
        cur_len=0

        def _add(t: str, e: List[dict]):
            nonlocal cur_len
            t, e = Dick.strip_with_entities(Dick.flat_text(t), e)
            if not t: return
            if parts_t:
                parts_e.extend(Dick.shift(e, cur_len + 1))
                parts_t.append(t)
                cur_len += 1 + Dick.u16(t)
            else:
                parts_e.extend(e)
                parts_t.append(t)
                cur_len = Dick.u16(t)

        if hasattr(b,"title") and getattr(b,"title",None):
            t,e=Dick.extract_rich_text(getattr(b,"title"))
            _add(t,e)
        if hasattr(b,"author") and getattr(b,"author",None):
            t,e=Dick.extract_rich_text(getattr(b,"author"))
            _add(t,e)
        if hasattr(b,"text") and getattr(b,"text",None):
            t,e=Dick.extract_rich_text(getattr(b,"text"))
            _add(t,e)
        if hasattr(b,"source") and getattr(b,"source",None):
            t,e=Dick.extract_rich_text(getattr(b,"source"))
            _add(t,e)
        if hasattr(b,"caption") and getattr(b,"caption",None):
            t,e=Dick.extract_rich_text(getattr(b,"caption"))
            _add(t,e)
        if hasattr(b,"cover") and getattr(b,"cover",None):
            t,e=Dick.extract_block_text(getattr(b,"cover"))
            _add(t,e)
        if hasattr(b,"items") and getattr(b,"items",None):
            for it in getattr(b,"items") or []:
                if hasattr(it,"text"):
                    t,e=Dick.extract_rich_text(getattr(it,"text"))
                else:
                    t,e=Dick.extract_block_text(it)
                _add(t,e)
        if hasattr(b,"rows") and getattr(b,"rows",None):
            for row in getattr(b,"rows") or []:
                for cell in getattr(row,"cells",[]) or []:
                    t,e=Dick.extract_rich_text(getattr(cell,"text",None))
                    _add(t,e)
        if hasattr(b,"blocks") and getattr(b,"blocks",None):
            for sub_b in getattr(b,"blocks") or []:
                t,e=Dick.extract_block_text(sub_b)
                _add(t,e)

        return " ".join(parts_t),parts_e

    @staticmethod
    def rich_preview_text(rich) -> Tuple[str,List[dict]]:
        if not rich: return "",[]
        blocks=getattr(rich,"blocks",None) or []
        parts_t: List[str]=[]
        parts_e: List[dict]=[]
        cur_len=0
        for b in blocks:
            t,e=Dick.extract_block_text(b)
            t,e=Dick.strip_with_entities(Dick.flat_text(t),e)
            if not t: continue
            if parts_t:
                parts_e.extend(Dick.shift(e,cur_len+1))
                parts_t.append(t)
                cur_len+=1+Dick.u16(t)
            else:
                parts_e.extend(e)
                parts_t.append(t)
                cur_len=Dick.u16(t)
        return " ".join(parts_t),parts_e

    @staticmethod
    def rich_thumbnail(rich):
        if not rich: return None
        photos=getattr(rich,"photos",None) or []
        documents=getattr(rich,"documents",None) or []
        photo_map={p.id:p for p in photos if getattr(p,"id",None) is not None}
        doc_map={d.id:d for d in documents if getattr(d,"id",None) is not None}
        for block in getattr(rich,"blocks",None) or []:
            if isinstance(block,types.PageBlockPhoto):
                p=photo_map.get(block.photo_id)
                if p: return p
            elif isinstance(block,types.PageBlockVideo):
                d=doc_map.get(block.video_id)
                if d and Dick.document_has_thumbnail(d): return d
            elif isinstance(block,types.PageBlockCover):
                cover=getattr(block,"cover",None)
                if isinstance(cover,types.PageBlockPhoto):
                    p=photo_map.get(cover.photo_id)
                    if p: return p
                elif isinstance(cover,types.PageBlockVideo):
                    d=doc_map.get(cover.video_id)
                    if d and Dick.document_has_thumbnail(d): return d
        if photos: return photos[0]
        for d in documents:
            if Dick.document_has_thumbnail(d): return d
        return None

    @staticmethod
    def rich_text(value) -> Tuple[str,List[dict]]:
        if value is None: return "",[]
        if isinstance(value,str): return Dick.flat_text(value),[]
        if isinstance(value,types.TypeRichText): return Dick.extract_rich_text(value)
        return Dick.flat_text(getattr(value,"text","")),Dick.ents(getattr(value,"entities",None))

    @staticmethod
    def document_has_thumbnail(document) -> bool:
        return bool(document and (getattr(document,"thumbs",None) or getattr(document,"video_thumbs",None)))

    @staticmethod
    def media_thumbnail(media):
        if isinstance(media,types.MessageMediaPhoto): return getattr(media,"photo",None)
        if isinstance(media,types.MessageMediaDocument):
            cover=getattr(media,"video_cover",None)
            document=getattr(media,"document",None)
            return cover or (document if Dick.document_has_thumbnail(document) else None)
        return None

    @staticmethod
    def reply_thumbnail(m: Message):
        media=getattr(m,"media",None)
        direct=Dick.media_thumbnail(media)
        if direct: return direct
        if isinstance(media,types.MessageMediaWebPage):
            page=getattr(media,"webpage",None)
            document=getattr(page,"document",None)
            if document:
                if getattr(document,"mime_type",None)=="application/x-tgwallpattern":
                    return None
                return document if Dick.document_has_thumbnail(document) else None
            return getattr(page,"photo",None)
        if isinstance(media,types.MessageMediaGame):
            game=getattr(media,"game",None)
            document=getattr(game,"document",None)
            if document:
                return document if Dick.document_has_thumbnail(document) else None
            return getattr(game,"photo",None)
        if isinstance(media,types.MessageMediaPoll): return Dick.media_thumbnail(getattr(media,"attached_media",None))
        if isinstance(media,types.MessageMediaInvoice): return getattr(media,"photo",None)
        rich=getattr(m,"rich_message",None)
        if rich: return Dick.rich_thumbnail(rich)
        return None

    @staticmethod
    def append_caption(label: str, caption: str, entities: List[dict], icon: Optional[str]=None,
                       has_thumbnail: bool=False) -> dict:
        if caption and has_thumbnail:
            return Dick.preview(caption,entities=entities,thumbnail=True)
        if label and caption:
            prefix=f"{label}, "
            shifted=[{"type":"media_type","offset":0,"length":Dick.u16(label)}]
            shifted.extend(Dick.shift(entities,Dick.u16(prefix)))
            return Dick.preview(prefix+caption,icon,shifted,has_thumbnail)
        label_entities=[{"type":"media_type","offset":0,"length":Dick.u16(label)}] if label else []
        return Dick.preview(label or caption,icon,label_entities if label else entities,has_thumbnail)

    @staticmethod
    def loc(strings, key: str, **kwargs) -> str:
        return strings[key].format(**kwargs)

    @staticmethod
    def call_preview(m: Message, strings) -> Optional[dict]:
        action=getattr(m,"action",None)
        if not Dick.is_type(action,"MessageActionPhoneCall"): return None
        outgoing=bool(getattr(m,"out",False))
        video=bool(getattr(action,"video",False))
        reason=getattr(action,"reason",None)
        missed=type(reason).__name__ in ("PhoneCallDiscardReasonMissed","PhoneCallDiscardReasonBusy")
        key=("call_missed_video" if video else "call_missed") if missed else (
              ("call_outgoing_video" if video else "call_outgoing") if outgoing
              else ("call_incoming_video" if video else "call_incoming"))
        label=Dick.loc(strings,key)
        duration=int(getattr(action,"duration",0) or 0)
        if duration: label=Dick.loc(strings,"call_with_duration",label=label,duration=Dick.dur(duration))
        icon=("video_call_outgoing" if outgoing else "video_call_incoming") if video else (
              "call_outgoing" if outgoing else "call_incoming")
        return Dick.preview(label,icon,[{"type":"media_type","offset":0,"length":Dick.u16(label)}])

    @staticmethod
    def service_preview(m: Message, strings) -> str:
        action=getattr(m,"action",None)
        custom=getattr(action,"message",None)
        if custom: return Dick.flat_text(custom)
        kind=type(action).__name__.replace("MessageAction","") if action else ""
        labels={"ChatEditPhoto":"service_preview_group_photo_updated",
                "ChatDeletePhoto":"service_preview_group_photo_removed",
                "ChatEditTitle":"service_preview_group_name_changed",
                "ChatCreate":"service_preview_group_created",
                "ChannelCreate":"service_preview_channel_created",
                "ChatAddUser":"service_preview_member_added",
                "ChatDeleteUser":"service_preview_member_removed",
                "ChatJoinedByLink":"service_preview_joined_by_link",
                "ChatJoinedByRequest":"service_preview_joined_by_request",
                "PinMessage":"service_preview_message_pinned",
                "ScreenshotTaken":"service_preview_screenshot_taken",
                "ContactSignUp":"service_preview_joined_telegram",
                "HistoryClear":"service_preview_history_cleared",
                "GroupCall":"service_preview_video_chat",
                "GroupCallScheduled":"service_preview_video_chat_scheduled",
                "SetMessagesTTL":"service_preview_auto_delete_changed",
                "TopicCreate":"service_preview_topic_created",
                "TopicEdit":"service_preview_topic_edited",
                "GiveawayLaunch":"service_preview_giveaway_started",
                "GiveawayResults":"service_preview_giveaway_results",
                "PaymentSent":"service_preview_payment_sent",
                "GiftPremium":"service_preview_premium_gift",
                "GiftStars":"service_preview_stars_gift"}
        return Dick.loc(strings,labels.get(kind,"service_message"))

    @staticmethod
    def media_preview(m: Message, strings) -> dict:
        raw=Dick.flat_text(getattr(m,"raw_text",None))
        raw_entities=Dick.ents(getattr(m,"entities",None))
        media=getattr(m,"media",None)
        thumbnail=Dick.reply_thumbnail(m)
        has_thumbnail=thumbnail is not None

        if Dick.is_type(m,"MessageService"):
            call=Dick.call_preview(m,strings)
            return call or Dick.preview(Dick.service_preview(m,strings))
        if m.photo: return Dick.append_caption(Dick.loc(strings,"media_photo"),raw,raw_entities,None,has_thumbnail)
        if m.sticker:
            emoji=getattr(getattr(m,"file",None),"emoji",None) or ""
            label=f"{emoji} {Dick.loc(strings,'media_sticker')}".strip()
            return Dick.preview(label,entities=[{"type":"media_type","offset":0,"length":Dick.u16(label)}],
                                thumbnail=has_thumbnail)
        if m.video_note: return Dick.append_caption(Dick.loc(strings,"media_video_message"),raw,raw_entities,None,has_thumbnail)
        if m.gif: return Dick.append_caption("GIF",raw,raw_entities,None,has_thumbnail)
        if m.video: return Dick.append_caption(Dick.loc(strings,"media_video"),raw,raw_entities,None,has_thumbnail)
        if m.voice: return Dick.append_caption(Dick.loc(strings,"media_voice_message"),raw,raw_entities,None,has_thumbnail)
        if m.audio:
            attr=next((a for a in (getattr(m.document,"attributes",[]) or []) if isinstance(a,types.DocumentAttributeAudio)),None)
            title=getattr(attr,"title",None) or getattr(getattr(m,"file",None),"name",None) or Dick.loc(strings,"media_audio_file")
            performer=getattr(attr,"performer",None)
            label=f"{performer} — {title}" if performer else title
            return Dick.append_caption(label,raw,raw_entities,None if has_thumbnail else "audio",has_thumbnail)
        if isinstance(media,types.MessageMediaDocument):
            label=getattr(getattr(m,"file",None),"name",None) or Dick.loc(strings,"media_file")
            return Dick.append_caption(label,raw,raw_entities,None if has_thumbnail else "document",has_thumbnail)
        if isinstance(media,(types.MessageMediaGeo,types.MessageMediaGeoLive,types.MessageMediaVenue)):
            label=Dick.loc(strings,"media_live_location" if isinstance(media,types.MessageMediaGeoLive) else "media_location")
            title=getattr(media,"title",None) or ""
            return Dick.append_caption(label,Dick.flat_text(title),[],"location",False)
        if isinstance(media,types.MessageMediaContact):
            label=Dick.loc(strings,"media_contact")
            return Dick.preview(label,"contact",[{"type":"media_type","offset":0,"length":Dick.u16(label)}])
        if isinstance(media,types.MessageMediaPoll):
            question,entities=Dick.rich_text(getattr(getattr(media,"poll",None),"question",None))
            return Dick.preview(question or Dick.loc(strings,"media_poll"),"poll",entities,has_thumbnail)
        if Dick.is_type(media,"MessageMediaToDo"):
            title,entities=Dick.rich_text(getattr(getattr(media,"todo",None),"title",None))
            if raw: return Dick.append_caption(title or Dick.loc(strings,"media_todo_list"),raw,raw_entities,"todo",False)
            return Dick.preview(title or Dick.loc(strings,"media_todo_list"),"todo",entities)
        if isinstance(media,types.MessageMediaDice):
            return Dick.preview(getattr(media,"emoticon",None) or Dick.loc(strings,"media_dice"))
        if isinstance(media,types.MessageMediaGame):
            title=getattr(getattr(media,"game",None),"title",None) or Dick.loc(strings,"media_game")
            return Dick.preview(title,"game",thumbnail=has_thumbnail)
        if isinstance(media,types.MessageMediaInvoice):
            title=getattr(media,"title",None) or Dick.loc(strings,"media_invoice")
            return Dick.preview(title,"invoice",thumbnail=has_thumbnail)
        if Dick.is_type(media,"MessageMediaPaidMedia"):
            return Dick.append_caption(Dick.loc(strings,"media_paid_media"),raw,raw_entities,"paid",has_thumbnail)
        if Dick.is_type(media,"MessageMediaStory"):
            story=getattr(media,"story",None)
            caption=Dick.flat_text(getattr(story,"caption",None))
            entities=Dick.ents(getattr(story,"entities",None))
            return Dick.append_caption(Dick.loc(strings,"media_story"),caption,entities,"story",False)
        if Dick.is_type(media,"MessageMediaGiveaway"):
            quantity=int(getattr(media,"quantity",0) or 0)
            label=Dick.loc(strings,"media_giveaway_prizes",count=quantity) if quantity else Dick.loc(strings,"media_giveaway")
            return Dick.preview(label,"giveaway")
        if Dick.is_type(media,"MessageMediaGiveawayResults"):
            winners=int(getattr(media,"winners_count",0) or 0)
            label=Dick.loc(strings,"media_giveaway_results") if not winners else Dick.loc(strings,"media_giveaway_winners",count=winners)
            return Dick.preview(label,"giveaway",[{"type":"media_type","offset":0,"length":Dick.u16(label)}])
        if Dick.is_type(media,"MessageMediaVideoStream"):
            return Dick.preview(Dick.loc(strings,"media_live_stream"),"video_stream")
        if isinstance(media,types.MessageMediaWebPage):
            page=getattr(media,"webpage",None)
            text=raw or Dick.flat_text(getattr(page,"url",None))
            return Dick.preview(text,entities=raw_entities if raw else [],thumbnail=has_thumbnail)
        if Dick.is_type(media,"MessageMediaUnsupported"):
            return Dick.preview(Dick.loc(strings,"media_unsupported"))
        rich=getattr(m,"rich_message",None)
        if rich:
            title,entities=Dick.rich_preview_text(rich)
            if not title and raw:
                title,entities=raw,raw_entities
            if has_thumbnail and not title:
                title=Dick.loc(strings,"media_photo")
                entities=[{"type":"media_type","offset":0,"length":Dick.u16(title)}]
            if has_thumbnail:
                return Dick.append_caption(Dick.loc(strings,"media_photo"),title,entities,None,has_thumbnail=True)
            if title:
                return Dick.preview(title,entities=entities,thumbnail=False)
            return Dick.preview(Dick.loc(strings,"reply_message"))
        return Dick.preview(raw,entities=raw_entities)

    @staticmethod
    def ents(es) -> List[dict]:
        out: List[dict]=[]
        if not es: return out
        for e in es:
            try:
                d=e.to_dict(); t=d.pop("_","").replace("MessageEntity","").lower()
                if not t: continue
                mt={"bold":"bold","italic":"italic","underline":"underline","strikethrough":"strikethrough",
                    "code":"code","pre":"pre","texturl":"text_link","url":"url","email":"email",
                    "phone":"phone_number","mention":"mention","mentionname":"text_mention",
                    "hashtag":"hashtag","cashtag":"cashtag","botcommand":"bot_command","spoiler":"spoiler",
                    "customemoji":"custom_emoji","formatteddate":"formatted_date"}.get(t,t)
                it={"type":mt,"offset":d.get("offset",0),"length":d.get("length",0)}
                if t=="blockquote" and d.get("collapsed"): it["type"]="expandable_blockquote"
                if t=="texturl": it["url"]=d.get("url","")
                elif t=="mentionname": it["user"]={"id":d.get("user_id",0)}
                elif t=="customemoji": it["custom_emoji_id"]=str(d.get("document_id",""))
                elif t=="pre": it["language"]=d.get("language","")
                elif t=="formatteddate":
                    date=d.get("date")
                    try: it["date"]=int(date.timestamp())
                    except Exception:
                        try: it["date"]=int(date)
                        except Exception: it["date"]=str(date or "")
                    for flag in ("relative","short_time","long_time","short_date","long_date","day_of_week"):
                        it[flag]=bool(d.get(flag,False))
                out.append(it)
            except Exception: continue
        return out

    @staticmethod
    def dur(s: Union[int,float]) -> str:
        t=gmtime(s); return (f"{t.tm_hour:02d}:" if t.tm_hour>0 else "")+f"{t.tm_min:02d}:{t.tm_sec:02d}"

    @staticmethod
    def split(name: Optional[str]) -> Tuple[str,str]:
        if not name: return "",""
        p=name.split(); return (p[0], " ".join(p[1:]) if len(p)>1 else "")

    @staticmethod
    def pick(m: Message):
        if m and m.media:
            location=m.media if isinstance(m.media,(types.MessageMediaGeo,types.MessageMediaGeoLive,
                                                    types.MessageMediaVenue)) else None
            return m.photo or m.sticker or m.video or m.video_note or m.gif or m.web_preview or location
        return None

    @staticmethod
    def wf(b: Optional[bytes]) -> List[int]:
        if not b: return []
        n=(len(b)*8)//5
        if not n: return []
        out: List[int]=[]
        for i in range(n):
            j=i*5; bi,sh=j//8,j%8
            v=int.from_bytes(b[bi:bi+2],"little") if bi+1<len(b) else b[bi]
            out.append((v>>sh)&0b11111)
        return out

    @staticmethod
    async def img(b: bytes, circle: bool=False, max_side: Optional[int]=None) -> Optional[str]:
        try:
            im=Image.open(io.BytesIO(b))
            if im.mode!="RGBA": im=im.convert("RGBA")
            if max_side and max(im.size)>max_side:
                im.thumbnail((max_side,max_side),getattr(Image,"Resampling",Image).LANCZOS)
            if circle:
                size=min(im.size)
                mask=Image.new("L",(size,size),0); ImageDraw.Draw(mask).ellipse((0,0,size,size),fill=255)
                sq=Image.new("RGBA",(size,size),(0,0,0,0))
                off=((size-im.width)//2,(size-im.height)//2);  sq.paste(im,off)
                im=Image.composite(sq,Image.new("RGBA",(size,size),(0,0,0,0)),mask)
            o=io.BytesIO(); im.save(o,format="PNG")
            return Dick.data(o.getvalue(),"image/png")
        except Exception:
            return None

    @staticmethod
    async def proc(cli, obj, m: Message) -> Optional[dict]:
        try:
            if isinstance(m.media,(types.MessageMediaGeo,types.MessageMediaGeoLive,types.MessageMediaVenue)):
                return await Dick.map_preview(cli,m.media.geo,width=512,height=320,zoom=13)
            b=await Dick.download(cli,obj)
            if not b: return None
            if m.sticker:
                u=await Dick.img(b); return {"url":u} if u else None
            u=await Dick.img(b,circle=bool(m.video_note))
            if u: return {"url":u}
            if m.gif or m.video:
                if len(b)>45*1024*1024: return None
                mime=getattr(m.file,"mime_type",None) or "application/octet-stream"
                return {"url":Dick.data(b,Dick.mime(b,mime))}
            return None
        except Exception:
            return None

    @staticmethod
    async def ava(cli, uid: int) -> Optional[str]:
        try:
            b=await cli.download_profile_photo(uid, bytes)
            if b: return Dick.data(b,"image/jpeg")
        except Exception: pass
        return None

    @staticmethod
    async def post(url: str, data: dict, proxy: Optional[str] = None):
        try:
            px={"http":proxy,"https":proxy} if proxy else None
            return await utils.run_sync(requests.post,url,json=data,timeout=(15,120),proxies=px),None
        except Exception as error:
            logger.exception("quote-api request failed: %s",url)
            detail=str(error).strip() or repr(error)
            if proxy: detail=detail.replace(proxy,"<proxy>")
            return None,f"{type(error).__name__}: {detail[:1200]}"

    @staticmethod
    def response_error(response) -> str:
        status=getattr(response,"status_code","?")
        reason=(getattr(response,"reason",None) or "").strip()
        prefix=f"HTTP {status}{' '+reason if reason else ''}"
        try:
            payload=response.json()
            if isinstance(payload,dict):
                detail=payload.get("error") or payload.get("message")
                if not detail: detail=str(payload)
            else: detail=str(payload)
        except Exception:
            detail=(getattr(response,"text",None) or "").strip()
        detail=" ".join(str(detail or "").split())[:1200]
        return f"{prefix}: {detail}" if detail else prefix

@loader.tds
class Quotes(loader.Module):
    strings = {
        "name": "yg_quotes",
        "no_reply": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Reply to a message or provide a link",
        "processing": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Processing…",
        "api_processing": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Waiting for the API response…",
        "api_error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> API error: {error}",
        "no_args_or_reply": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> No arguments or reply",
        "args_error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Could not parse the arguments. Request: <code>{request}</code>",
        "too_many_messages": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Too many messages. Maximum: <code>{maximum}</code>",
        "error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Error: {error}",
        "network_error": "Network error (try setting a proxy in the config)",
        "parse_collect_error": "Could not collect messages",
        "parse_empty_list": "Telegram returned an empty list of messages",
        "parse_sender_not_found": "Message sender was not found: {message_id} ({message_type}, from_id={from_id})",
        "parse_messages_not_collected": "Messages were received but could not be collected: {ids}",
        "cfg_type": "Quote type",
        "cfg_bg_color": "Quote background color (for example, #1a1a1a or red)",
        "cfg_width": "Quote width (px)",
        "cfg_height": "Quote height (px)",
        "cfg_scale": "Render scale",
        "cfg_ui_scale": "Interface scale (%, default: 100)",
        "cfg_emoji_brand": "Emoji style (apple, google, twitter, etc.)",
        "cfg_max_messages": "Maximum number of messages in a quote",
        "cfg_endpoint": "API endpoint URL (you can host it locally: github.com/yummy1gay/quote-api)",
        "cfg_proxy": "Proxy to bypass blocks (for example: http://user:pass@ip:port). Leave blank if it is not needed.",
        "call_missed_video": "Missed video call",
        "call_missed": "Missed call",
        "call_outgoing_video": "Outgoing video call",
        "call_outgoing": "Outgoing call",
        "call_incoming_video": "Incoming video call",
        "call_incoming": "Incoming call",
        "call_with_duration": "{label}, {duration}",
        "media_photo": "Photo",
        "media_sticker": "Sticker",
        "media_video_message": "Video message",
        "media_video": "Video",
        "media_voice_message": "Voice message",
        "media_audio_file": "Audio file",
        "media_file": "File",
        "media_live_location": "Live location",
        "media_location": "Location",
        "media_contact": "Contact",
        "media_poll": "Poll",
        "media_todo_list": "To-do list",
        "media_dice": "Dice",
        "media_game": "Game",
        "media_invoice": "Invoice",
        "media_paid_media": "Paid media",
        "media_story": "Story",
        "media_giveaway": "Giveaway",
        "media_giveaway_prizes": "{count} prizes",
        "media_giveaway_results": "Giveaway results",
        "media_giveaway_winners": "{count} winners",
        "media_live_stream": "Live stream",
        "media_unsupported": "Unsupported media",
        "reply_message": "Message",
        "sender_tag_owner": "owner",
        "sender_tag_admin": "admin",
        "sender_tag_member": "member",
        "telegram": "Telegram",
        "someone": "Someone",
        "bot": "a bot",
        "community": "a community",
        "service_message": "Service message",
        "quote": "“{value}”",
        "join_two": "{first} and {second}",
        "join_many": "{prefix}, and {last}",
        "duration_day_one": "{count} day",
        "duration_day_few": "{count} days",
        "duration_day_many": "{count} days",
        "duration_hour_one": "{count} hour",
        "duration_hour_few": "{count} hours",
        "duration_hour_many": "{count} hours",
        "duration_minute_one": "{count} minute",
        "duration_minute_few": "{count} minutes",
        "duration_minute_many": "{count} minutes",
        "duration_second_one": "{count} second",
        "duration_second_few": "{count} seconds",
        "duration_second_many": "{count} seconds",
        "stars_one": "{count} Star",
        "stars_few": "{count} Stars",
        "stars_many": "{count} Stars",
        "service_group_created": "{actor} created the group {title}",
        "service_channel_created": "Channel created",
        "service_group_name_changed": "{actor} changed the group name to {title}",
        "service_channel_name_changed": "Channel name was changed to {title}",
        "service_group_photo_updated": "{actor} updated group photo",
        "service_group_photo_removed": "{actor} removed group photo",
        "service_channel_photo_updated": "Channel photo updated",
        "service_channel_photo_removed": "Channel photo removed",
        "service_user_joined": "{actor} joined the group",
        "service_user_added": "{actor} added {users}",
        "service_user_removed": "{actor} removed {user}",
        "service_user_left": "{actor} left the group",
        "service_joined_by_link": "{actor} joined the group via invite link",
        "service_joined_by_request": "{actor} was accepted to the group",
        "service_joined_via_community": "{actor} joined the group via the {community} community",
        "service_group_migrated": "This group was upgraded to a supergroup",
        "service_group_migrated_named": "Group {title} was upgraded to a supergroup",
        "service_pinned_message": "{actor} pinned {message}",
        "service_pinned_media": "{actor} pinned {media}",
        "pinned_media_message": "a message",
        "pinned_media_photo": "a photo",
        "pinned_media_video": "a video",
        "pinned_media_audio": "an audio file",
        "pinned_media_voice": "a voice message",
        "pinned_media_video_message": "a video message",
        "pinned_media_file": "a file",
        "pinned_media_gif": "a GIF",
        "pinned_media_contact": "a contact information",
        "pinned_media_location": "a location mark",
        "pinned_media_sticker": "a sticker",
        "pinned_media_game": "a game",
        "pinned_media_story": "a story",
        "service_history_cleared": "Chat history was cleared",
        "service_score_one": "{actor} scored {count} point",
        "service_score_few": "{actor} scored {count} points",
        "service_score_many": "{actor} scored {count} points",
        "service_payment_received": "Payment received",
        "service_payment_sent": "{actor} sent a payment",
        "service_payment_amount": "{text} of {amount}",
        "service_screenshot_you": "You took a screenshot",
        "service_screenshot": "{actor} took a screenshot",
        "service_bot_allowed_domain": "You allowed this bot to message you when you logged in on {domain}",
        "service_bot_allowed": "You allowed this bot to send messages",
        "service_passport_shared": "Telegram Passport data was shared",
        "service_joined_telegram": "{actor} joined Telegram",
        "distance_meter_one": "{count} meter",
        "distance_meter_few": "{count} meters",
        "distance_meter_many": "{count} meters",
        "distance_kilometer_one": "{count} km",
        "distance_kilometer_few": "{count} km",
        "distance_kilometer_many": "{count} km",
        "service_proximity": "{first} is now within {distance} from {second}",
        "service_video_chat_started": "{actor} started a video chat",
        "service_live_stream_started": "Live stream started",
        "service_video_chat_finished": "{actor} ended the video chat ({duration})",
        "service_live_stream_finished": "Live stream finished ({duration})",
        "service_video_chat_invited": "{actor} invited {users} to the video chat",
        "service_ttl_changed": "{actor} set messages to auto-delete in {duration}",
        "service_ttl_changed_you": "You set messages to auto-delete in {duration}",
        "service_ttl_disabled": "{actor} disabled the auto-delete timer",
        "service_ttl_disabled_you": "You disabled the auto-delete timer",
        "service_video_chat_scheduled": "{actor} scheduled a video chat for {date}",
        "service_live_stream_scheduled": "Live stream scheduled for {date}",
        "service_date_format": "{date:%b %d, %Y at %H:%M}",
        "service_later": "later",
        "service_theme_changed": "{actor} changed the chat theme to {theme}",
        "service_theme_changed_you": "You changed the chat theme to {theme}",
        "service_theme_disabled": "{actor} disabled the chat theme",
        "service_theme_disabled_you": "You disabled the chat theme",
        "service_webview_data": "Data from the “{value}” button was transferred to the bot",
        "service_webview_data_empty": "Data was transferred to the bot",
        "service_premium_gift": "{actor} sent a Telegram Premium gift",
        "topic_placeholder": "topic",
        "service_topic_created": "The topic {title} was created",
        "service_topic_created_icon": "The topic {icon} {title} was created",
        "service_topic_closed": "{actor} closed the topic",
        "service_topic_reopened": "{actor} reopened the topic",
        "service_topic_hidden": "The topic was hidden",
        "service_topic_unhidden": "The topic was unhidden",
        "service_topic_renamed": "{actor} renamed the topic to {title}",
        "service_topic_icon_changed": "{actor} changed the topic icon",
        "service_topic_updated": "Topic updated",
        "service_profile_photo_suggested": "{actor} suggested a new profile photo",
        "service_contact_shared": "Requested contact information was shared",
        "service_wallpaper_changed": "{actor} set a new wallpaper for this chat",
        "gift_code": "a gift code",
        "gift_stars": "a Stars gift",
        "gift_ton": "a TON gift",
        "gift": "a gift",
        "gift_collectible": "a collectible gift",
        "service_gift_sent": "{actor} sent {gift}",
        "service_giveaway_prize": "Giveaway prize received",
        "service_payment_refunded": "Payment refunded",
        "service_with_amount": "{text}: {amount}",
        "service_giveaway_started": "Giveaway started",
        "service_giveaway_finished": "Giveaway finished",
        "service_giveaway_finished_one": "Giveaway finished with {count} winner",
        "service_giveaway_finished_few": "Giveaway finished with {count} winners",
        "service_giveaway_finished_many": "Giveaway finished with {count} winners",
        "service_channel_boosted": "{actor} boosted the channel",
        "service_channel_boosted_one": "{actor} boosted the channel {count} time",
        "service_channel_boosted_few": "{actor} boosted the channel {count} times",
        "service_channel_boosted_many": "{actor} boosted the channel {count} times",
        "service_paid_refund_one": "Payment for {count} message was refunded",
        "service_paid_refund_few": "Payment for {count} messages was refunded",
        "service_paid_refund_many": "Payment for {count} messages was refunded",
        "service_paid_price_one": "Paid message price changed to {count} Star",
        "service_paid_price_few": "Paid message price changed to {count} Stars",
        "service_paid_price_many": "Paid message price changed to {count} Stars",
        "service_missed_video_call": "Missed video call",
        "service_missed_call": "Missed call",
        "service_video_call_ended": "Video call ended",
        "service_call_ended": "Call ended",
        "service_call_ended_duration": "{text}, {duration}",
        "service_todo_completed_one": "{actor} completed {count} task",
        "service_todo_completed_few": "{actor} completed {count} tasks",
        "service_todo_completed_many": "{actor} completed {count} tasks",
        "service_todo_reopened_one": "{actor} reopened {count} task",
        "service_todo_reopened_few": "{actor} reopened {count} tasks",
        "service_todo_reopened_many": "{actor} reopened {count} tasks",
        "service_todo_updated": "To-do list updated",
        "service_todo_added_one": "{actor} added {count} task",
        "service_todo_added_few": "{actor} added {count} tasks",
        "service_todo_added_many": "{actor} added {count} tasks",
        "service_suggested_post_reviewed": "Suggested post reviewed",
        "service_suggested_post_published": "Suggested post published",
        "service_suggested_post_refunded": "Suggested post payment refunded",
        "service_suggested_post_updated": "Suggested post updated",
        "service_birthday_suggested": "{actor} suggested a birthday",
        "service_gift_offer_updated": "Gift purchase offer updated",
        "service_ownership_pending": "Ownership transfer to {user} is pending",
        "service_new_owner": "{user} is now the owner",
        "service_content_protection_enabled": "Content protection enabled",
        "service_content_protection_disabled": "Content protection disabled",
        "service_poll_option_added": "{actor} added a poll option{option}",
        "service_poll_option_removed": "{actor} removed a poll option{option}",
        "service_option_suffix": ": {option}",
        "service_managed_bot_created": "{actor} created a bot {bot}",
        "service_chat_linked": "This chat was linked to {community}",
        "service_chat_unlinked": "This chat was unlinked from its community",
        "service_preview_group_photo_updated": "Group photo updated",
        "service_preview_group_photo_removed": "Group photo removed",
        "service_preview_group_name_changed": "Group name changed",
        "service_preview_group_created": "Group created",
        "service_preview_channel_created": "Channel created",
        "service_preview_member_added": "Member added",
        "service_preview_member_removed": "Member removed",
        "service_preview_joined_by_link": "Joined via invite link",
        "service_preview_joined_by_request": "Join request approved",
        "service_preview_message_pinned": "Message pinned",
        "service_preview_screenshot_taken": "Screenshot taken",
        "service_preview_joined_telegram": "Joined Telegram",
        "service_preview_history_cleared": "History cleared",
        "service_preview_video_chat": "Video chat",
        "service_preview_video_chat_scheduled": "Video chat scheduled",
        "service_preview_auto_delete_changed": "Auto-delete timer changed",
        "service_preview_topic_created": "Topic created",
        "service_preview_topic_edited": "Topic edited",
        "service_preview_giveaway_started": "Giveaway started",
        "service_preview_giveaway_results": "Giveaway results",
        "service_preview_payment_sent": "Payment sent",
        "service_preview_premium_gift": "Telegram Premium gift",
        "service_preview_stars_gift": "Stars gift"
    }

    strings_ru = {
        "name": "yg_quotes",
        "no_reply": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Ответьте на сообщение или укажите ссылку",
        "processing": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Обработка…",
        "api_processing": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Ожидание ответа API…",
        "api_error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Ошибка API: {error}",
        "no_args_or_reply": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Нет аргументов или ответа на сообщение",
        "args_error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Не удалось разобрать аргументы. Запрос: <code>{request}</code>",
        "too_many_messages": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Слишком много сообщений. Максимум: <code>{maximum}</code>",
        "error": "<emoji document_id=6321272741005624970>🏳️‍🌈</emoji> Ошибка: {error}",
        "network_error": "Ошибка сети (попробуйте указать прокси в настройках)",
        "parse_collect_error": "Не удалось собрать сообщения",
        "parse_empty_list": "Telegram вернул пустой список сообщений",
        "parse_sender_not_found": "Не найден отправитель сообщения: {message_id} ({message_type}, from_id={from_id})",
        "parse_messages_not_collected": "Сообщения получены, но их не удалось собрать: {ids}",
        "cfg_type": "Тип цитаты",
        "cfg_bg_color": "Цвет фона цитаты (например, #1a1a1a или red)",
        "cfg_width": "Ширина цитаты (px)",
        "cfg_height": "Высота цитаты (px)",
        "cfg_scale": "Масштаб рендера",
        "cfg_ui_scale": "Масштаб интерфейса (%, по умолчанию: 100)",
        "cfg_emoji_brand": "Стиль эмодзи (apple, google, twitter и т. д.)",
        "cfg_max_messages": "Максимальное число сообщений в цитате",
        "cfg_endpoint": "URL API-эндпоинта (можно поднять локально: github.com/yummy1gay/quote-api)",
        "cfg_proxy": "Прокси для обхода блокировок (например: http://user:pass@ip:port). Оставьте пустым, если он не нужен.",
        "call_missed_video": "Пропущенный видеозвонок",
        "call_missed": "Пропущенный звонок",
        "call_outgoing_video": "Исходящий видеозвонок",
        "call_outgoing": "Исходящий звонок",
        "call_incoming_video": "Входящий видеозвонок",
        "call_incoming": "Входящий звонок",
        "call_with_duration": "{label}, {duration}",
        "media_photo": "Фото",
        "media_sticker": "Стикер",
        "media_video_message": "Видеосообщение",
        "media_video": "Видео",
        "media_voice_message": "Голосовое сообщение",
        "media_audio_file": "Аудиофайл",
        "media_file": "Файл",
        "media_live_location": "Геопозиция в реальном времени",
        "media_location": "Геопозиция",
        "media_contact": "Контакт",
        "media_poll": "Опрос",
        "media_todo_list": "Список задач",
        "media_dice": "Кубик",
        "media_game": "Игра",
        "media_invoice": "Счёт",
        "media_paid_media": "Платный контент",
        "media_story": "История",
        "media_giveaway": "Розыгрыш",
        "media_giveaway_prizes": "{count} призов",
        "media_giveaway_results": "Итоги розыгрыша",
        "media_giveaway_winners": "{count} победителей",
        "media_live_stream": "Трансляция",
        "media_unsupported": "Неподдерживаемый медиафайл",
        "reply_message": "Сообщение",
        "sender_tag_owner": "владелец",
        "sender_tag_admin": "администратор",
        "sender_tag_member": "участник",
        "telegram": "Telegram",
        "someone": "Кто-то",
        "bot": "бот",
        "community": "сообщество",
        "service_message": "Сервисное сообщение",
        "quote": "«{value}»",
        "join_two": "{first} и {second}",
        "join_many": "{prefix} и {last}",
        "duration_day_one": "{count} день",
        "duration_day_few": "{count} дня",
        "duration_day_many": "{count} дней",
        "duration_hour_one": "{count} час",
        "duration_hour_few": "{count} часа",
        "duration_hour_many": "{count} часов",
        "duration_minute_one": "{count} минуту",
        "duration_minute_few": "{count} минуты",
        "duration_minute_many": "{count} минут",
        "duration_second_one": "{count} секунду",
        "duration_second_few": "{count} секунды",
        "duration_second_many": "{count} секунд",
        "stars_one": "{count} Звезда",
        "stars_few": "{count} Звезды",
        "stars_many": "{count} Звёзд",
        "service_group_created": "{actor} создал(а) группу {title}",
        "service_channel_created": "Канал создан",
        "service_group_name_changed": "{actor} изменил(а) название группы на {title}",
        "service_channel_name_changed": "Название канала изменено на {title}",
        "service_group_photo_updated": "{actor} обновил(а) фото группы",
        "service_group_photo_removed": "{actor} удалил(а) фото группы",
        "service_channel_photo_updated": "Фото канала обновлено",
        "service_channel_photo_removed": "Фото канала удалено",
        "service_user_joined": "{actor} присоединился(-ась) к группе",
        "service_user_added": "{actor} добавил(а) {users}",
        "service_user_removed": "{actor} удалил(а) {user}",
        "service_user_left": "{actor} покинул(а) группу",
        "service_joined_by_link": "{actor} присоединился(-ась) к группе по пригласительной ссылке",
        "service_joined_by_request": "Заявка {actor} на вступление в группу одобрена",
        "service_joined_via_community": "{actor} присоединился(-ась) к группе через сообщество {community}",
        "service_group_migrated": "Эта группа была преобразована в супергруппу",
        "service_group_migrated_named": "Группа {title} была преобразована в супергруппу",
        "service_pinned_message": "{actor} закрепил(а) {message}",
        "service_pinned_media": "{actor} закрепил(а) {media}",
        "pinned_media_message": "сообщение",
        "pinned_media_photo": "фотографию",
        "pinned_media_video": "видео",
        "pinned_media_audio": "аудиофайл",
        "pinned_media_voice": "голосовое сообщение",
        "pinned_media_video_message": "видеосообщение",
        "pinned_media_file": "файл",
        "pinned_media_gif": "GIF",
        "pinned_media_contact": "контакт",
        "pinned_media_location": "геопозицию",
        "pinned_media_sticker": "стикер",
        "pinned_media_game": "игру",
        "pinned_media_story": "историю",
        "service_history_cleared": "История чата очищена",
        "service_score_one": "{actor} набрал(а) {count} очко",
        "service_score_few": "{actor} набрал(а) {count} очка",
        "service_score_many": "{actor} набрал(а) {count} очков",
        "service_payment_received": "Платёж получен",
        "service_payment_sent": "{actor} отправил(а) платёж",
        "service_payment_amount": "{text} на сумму {amount}",
        "service_screenshot_you": "Вы сделали скриншот",
        "service_screenshot": "{actor} сделал(а) скриншот",
        "service_bot_allowed_domain": "Вы разрешили этому боту писать вам при входе на {domain}",
        "service_bot_allowed": "Вы разрешили этому боту отправлять вам сообщения",
        "service_passport_shared": "Данные Telegram Passport были переданы",
        "service_joined_telegram": "{actor} присоединился(-ась) к Telegram",
        "distance_meter_one": "{count} метр",
        "distance_meter_few": "{count} метра",
        "distance_meter_many": "{count} метров",
        "distance_kilometer_one": "{count} км",
        "distance_kilometer_few": "{count} км",
        "distance_kilometer_many": "{count} км",
        "service_proximity": "{first} сейчас находится на расстоянии {distance} от {second}",
        "service_video_chat_started": "{actor} начал(а) видеочат",
        "service_live_stream_started": "Трансляция началась",
        "service_video_chat_finished": "{actor} завершил(а) видеочат ({duration})",
        "service_live_stream_finished": "Трансляция завершилась ({duration})",
        "service_video_chat_invited": "{actor} пригласил(а) {users} в видеочат",
        "service_ttl_changed": "{actor} включил(а) автоудаление сообщений через {duration}",
        "service_ttl_changed_you": "Вы включили автоудаление сообщений через {duration}",
        "service_ttl_disabled": "{actor} отключил(а) автоудаление сообщений",
        "service_ttl_disabled_you": "Вы отключили автоудаление сообщений",
        "service_video_chat_scheduled": "{actor} запланировал(а) видеочат на {date}",
        "service_live_stream_scheduled": "Трансляция запланирована на {date}",
        "service_date_format": "{date:%d.%m.%Y в %H:%M}",
        "service_later": "позже",
        "service_theme_changed": "{actor} изменил(а) тему чата на {theme}",
        "service_theme_changed_you": "Вы изменили тему чата на {theme}",
        "service_theme_disabled": "{actor} отключил(а) тему чата",
        "service_theme_disabled_you": "Вы отключили тему чата",
        "service_webview_data": "Данные кнопки «{value}» переданы боту",
        "service_webview_data_empty": "Данные переданы боту",
        "service_premium_gift": "{actor} отправил(а) подарок Telegram Premium",
        "topic_placeholder": "тема",
        "service_topic_created": "Тема {title} создана",
        "service_topic_created_icon": "Тема {icon} {title} создана",
        "service_topic_closed": "{actor} закрыл(а) тему",
        "service_topic_reopened": "{actor} снова открыл(а) тему",
        "service_topic_hidden": "Тема скрыта",
        "service_topic_unhidden": "Тема снова отображается",
        "service_topic_renamed": "{actor} переименовал(а) тему в {title}",
        "service_topic_icon_changed": "{actor} изменил(а) значок темы",
        "service_topic_updated": "Тема обновлена",
        "service_profile_photo_suggested": "{actor} предложил(а) новое фото профиля",
        "service_contact_shared": "Запрошенные контактные данные переданы",
        "service_wallpaper_changed": "{actor} установил(а) новый фон для этого чата",
        "gift_code": "подарочный код",
        "gift_stars": "подарок в Звёздах",
        "gift_ton": "подарок в TON",
        "gift": "подарок",
        "gift_collectible": "коллекционный подарок",
        "service_gift_sent": "{actor} отправил(а) {gift}",
        "service_giveaway_prize": "Получен приз в розыгрыше",
        "service_payment_refunded": "Платёж возвращён",
        "service_with_amount": "{text}: {amount}",
        "service_giveaway_started": "Розыгрыш начался",
        "service_giveaway_finished": "Розыгрыш завершён",
        "service_giveaway_finished_one": "Розыгрыш завершён: {count} победитель",
        "service_giveaway_finished_few": "Розыгрыш завершён: {count} победителя",
        "service_giveaway_finished_many": "Розыгрыш завершён: {count} победителей",
        "service_channel_boosted": "{actor} поддержал(а) канал бустом",
        "service_channel_boosted_one": "{actor} поддержал(а) канал бустом {count} раз",
        "service_channel_boosted_few": "{actor} поддержал(а) канал бустом {count} раза",
        "service_channel_boosted_many": "{actor} поддержал(а) канал бустом {count} раз",
        "service_paid_refund_one": "Возвращена оплата за {count} сообщение",
        "service_paid_refund_few": "Возвращена оплата за {count} сообщения",
        "service_paid_refund_many": "Возвращена оплата за {count} сообщений",
        "service_paid_price_one": "Цена платного сообщения изменена на {count} Звезду",
        "service_paid_price_few": "Цена платного сообщения изменена на {count} Звезды",
        "service_paid_price_many": "Цена платного сообщения изменена на {count} Звёзд",
        "service_missed_video_call": "Пропущенный видеозвонок",
        "service_missed_call": "Пропущенный звонок",
        "service_video_call_ended": "Видеозвонок завершён",
        "service_call_ended": "Звонок завершён",
        "service_call_ended_duration": "{text}, {duration}",
        "service_todo_completed_one": "{actor} отметил(а) {count} задачу как выполненную",
        "service_todo_completed_few": "{actor} отметил(а) {count} задачи как выполненные",
        "service_todo_completed_many": "{actor} отметил(а) {count} задач как выполненные",
        "service_todo_reopened_one": "{actor} снова открыл(а) {count} задачу",
        "service_todo_reopened_few": "{actor} снова открыл(а) {count} задачи",
        "service_todo_reopened_many": "{actor} снова открыл(а) {count} задач",
        "service_todo_updated": "Список задач обновлён",
        "service_todo_added_one": "{actor} добавил(а) {count} задачу",
        "service_todo_added_few": "{actor} добавил(а) {count} задачи",
        "service_todo_added_many": "{actor} добавил(а) {count} задач",
        "service_suggested_post_reviewed": "Предложенный пост рассмотрен",
        "service_suggested_post_published": "Предложенный пост опубликован",
        "service_suggested_post_refunded": "Оплата предложенного поста возвращена",
        "service_suggested_post_updated": "Предложенный пост обновлён",
        "service_birthday_suggested": "{actor} предложил(а) дату рождения",
        "service_gift_offer_updated": "Предложение о покупке подарка обновлено",
        "service_ownership_pending": "Передача прав владельца пользователю {user} ожидает подтверждения",
        "service_new_owner": "{user} теперь владелец",
        "service_content_protection_enabled": "Защита контента включена",
        "service_content_protection_disabled": "Защита контента отключена",
        "service_poll_option_added": "{actor} добавил(а) вариант ответа в опрос{option}",
        "service_poll_option_removed": "{actor} удалил(а) вариант ответа из опроса{option}",
        "service_option_suffix": ": {option}",
        "service_managed_bot_created": "{actor} создал(а) бота {bot}",
        "service_chat_linked": "Этот чат связан с сообществом {community}",
        "service_chat_unlinked": "Этот чат больше не связан с сообществом",
        "service_preview_group_photo_updated": "Фото группы обновлено",
        "service_preview_group_photo_removed": "Фото группы удалено",
        "service_preview_group_name_changed": "Название группы изменено",
        "service_preview_group_created": "Группа создана",
        "service_preview_channel_created": "Канал создан",
        "service_preview_member_added": "Участник добавлен",
        "service_preview_member_removed": "Участник удалён",
        "service_preview_joined_by_link": "Вступление по пригласительной ссылке",
        "service_preview_joined_by_request": "Заявка на вступление одобрена",
        "service_preview_message_pinned": "Сообщение закреплено",
        "service_preview_screenshot_taken": "Скриншот сделан",
        "service_preview_joined_telegram": "Присоединился(-ась) к Telegram",
        "service_preview_history_cleared": "История очищена",
        "service_preview_video_chat": "Видеочат",
        "service_preview_video_chat_scheduled": "Видеочат запланирован",
        "service_preview_auto_delete_changed": "Таймер автоудаления изменён",
        "service_preview_topic_created": "Тема создана",
        "service_preview_topic_edited": "Тема изменена",
        "service_preview_giveaway_started": "Розыгрыш начался",
        "service_preview_giveaway_results": "Итоги розыгрыша",
        "service_preview_payment_sent": "Платёж отправлен",
        "service_preview_premium_gift": "Подарок Telegram Premium",
        "service_preview_stars_gift": "Подарок в Звёздах",
        "_cls_doc": "Модуль для создания цитат из сообщений",
        "_cmd_doc_q": """Обычные цитаты:
        • .q — процитировать одно сообщение из реплая
        • .q <ссылка> — процитировать сообщение по ссылке (t.me/...)
        • .q <ссылка> 3 — процитировать 3 сообщения начиная со ссылки
        • .q 2 — процитировать 2 сообщения
        • .q 3 #2d2d2d — 3 сообщения на тёмном фоне
        • .q pink — фон по имени цвета
        • .q !file — отправить как файл (PNG)""",
        "_cmd_doc_fq": """Фейковые цитаты:
        • .fq <@ или ID> <текст> — цитата от пользователя
        • .fq <reply> <текст> — цитата от автора реплая
        • .fq <@/ID> <текст> -r <@/ID> <текст> — с ответом
        • .fq user1 текст; user2 текст — несколько сообщений""",
    }

    def __init__(self):
        self.config=loader.ModuleConfig(
        loader.ConfigValue("type","quote",
                            lambda:self.strings("cfg_type"),
                            validator=loader.validators.Choice(["quote", "image", "stories"])),
        loader.ConfigValue("bg_color","#162330",
                            lambda:self.strings("cfg_bg_color")),
        loader.ConfigValue("width",512,
                            lambda:self.strings("cfg_width"),
                            validator=loader.validators.Integer(minimum=200,maximum=2000)),
        loader.ConfigValue("height",768,
                            lambda:self.strings("cfg_height"),
                            validator=loader.validators.Integer(minimum=200,maximum=2000)),
        loader.ConfigValue("scale",2,
                            lambda:self.strings("cfg_scale"),
                            validator=loader.validators.Choice([1, 2, 3, 4, 5])),
        loader.ConfigValue("ui_scale",100,
                            lambda:self.strings("cfg_ui_scale"),
                            validator=loader.validators.Integer(minimum=50,maximum=300)),
        loader.ConfigValue("emoji_brand","apple",
                            lambda:self.strings("cfg_emoji_brand")),
        loader.ConfigValue("max_messages",15,
                            lambda:self.strings("cfg_max_messages"),
                            validator=loader.validators.Integer(minimum=1,maximum=50)),
        loader.ConfigValue("endpoint","https://kok.gay/gayotes/generate",
                            lambda:self.strings("cfg_endpoint"),
                            validator=loader.validators.Link()),
        loader.ConfigValue("proxy", "",
                            lambda:self.strings("cfg_proxy")))

    async def client_ready(self, client, db):
        self.client=client; self.db=db

    async def _history(self,entity,offset_id,limit):
        return [message async for message in self.client.iter_messages(
            entity,limit=max(1,min(int(limit),100)),reverse=True,
            add_offset=1,offset_id=offset_id
        )]

    async def _peer_colors(self,hash=0):
        request=getattr(functions.help,"GetPeerColorsRequest",None)
        if request is None: return None
        return await self.client(request(hash=hash))

    def _payload(self, messages: List[dict], background: str, ext: str) -> dict:
        return {"backgroundColor":background,"width":self.config["width"],"height":self.config["height"],
                "scale":self.config["scale"],"uiScale":self.config["ui_scale"],
                "emojiBrand":self.config["emoji_brand"],"messages":messages,
                "format":ext,"type":self.config["type"]}

    async def _render(self, status: Message, messages: List[dict], background: str, ext: str,
                      document: bool=False):
        await utils.answer(status,self.strings["api_processing"])
        response,error=await Dick.post(f"{self.config['endpoint']}.{ext}",
                                       self._payload(messages,background,ext),self.config["proxy"] or None)
        if error or response is None:
            error=error or self.strings["network_error"]
            return await utils.answer(status,self.strings["api_error"].format(error=utils.escape_html(error)))
        if response.status_code!=200:
            error=Dick.response_error(response)
            return await utils.answer(status,self.strings["api_error"].format(error=utils.escape_html(error)))
        buf=io.BytesIO(response.content); buf.name=f"YgQuote.{ext}"
        return await utils.answer(status,buf,force_document=document)

    async def qcmd(self, m: Message):
        try:
            args=utils.get_args(m); rep=await m.get_reply_message()
            link_arg=None; link_info=None
            for arg in args:
                parsed=Dick.parse_msg_link(arg)
                if parsed: link_arg=arg; link_info=parsed; break
            if not rep and not link_info: return await utils.answer(m,self.strings["no_reply"])

            st=await utils.answer(m,self.strings["processing"])
            doc="!file" in args
            n=next((int(arg) for arg in args if arg.isdigit() and int(arg)>0),1)
            bg=next((arg for arg in args if arg not in ("!file",link_arg) and not arg.isdigit()),self.config["bg_color"])
            if n>self.config["max_messages"]:
                return await utils.answer(st,self.strings["too_many_messages"].format(maximum=self.config["max_messages"]))

            js=await self.parse(m,n,link_info)
            if not js:
                detail=getattr(self,"_last_parse_error","")
                error=self.strings["parse_collect_error"]+(f": {detail}" if detail else "")
                return await utils.answer(st,self.strings["api_error"].format(error=utils.escape_html(error)))

            ext="webp" if self.config["type"]=="quote" and not doc else "png"
            return await self._render(st,js,bg,ext,doc)
        except Exception as e:
            return await utils.answer(m,self.strings["error"].format(error=utils.escape_html(str(e))))

    async def fqcmd(self, m: Message):
        try:
            raw=utils.get_args_html(m); rep=await m.get_reply_message()
            if not (raw or rep): return await utils.answer(m,self.strings["no_args_or_reply"])
            st= await utils.answer(m,self.strings["processing"])
            try: js=await self.fake(raw,rep)
            except (IndexError,ValueError): return await utils.answer(st,self.strings["args_error"].format(request=m.text))
            if len(js)>self.config["max_messages"]:
                return await utils.answer(st,self.strings["too_many_messages"].format(maximum=self.config["max_messages"]))

            ext="webp" if self.config["type"]=="quote" else "png"
            return await self._render(st,js,self.config["bg_color"],ext)
        except Exception as e:
            return await utils.answer(m,self.strings["error"].format(error=utils.escape_html(str(e))))

    async def peer_palettes(self) -> Optional[dict]:
        if getattr(functions.help,"GetPeerColorsRequest",None) is None:
            return None

        colors=[0xcc5049,0xd67722,0x955cdb,0x40a920,0x309eba,0x368ad1,0xc7508b]
        palettes={index:{"colors":[color],"dark_colors":[]} for index,color in enumerate(colors)}
        available=await self._peer_colors(hash=0)
        options=getattr(available,"colors",[]) or []
        if not options: return None
        for option in options:
            light=Dick.color_pack(option.colors)
            if light:
                palettes[option.color_id]={"colors":light,"dark_colors":Dick.color_pack(option.dark_colors)}
        return palettes

    @staticmethod
    def tag_text(value) -> str:
        value=" ".join(Dick.flat_text(value).split())
        if not value: return ""
        result=[]
        for char in value:
            code=ord(char)
            if (0x1F000<=code<=0x1FAFF or 0x2600<=code<=0x27BF or 0x1F1E6<=code<=0x1F1FF
                    or code in (0x200D,0x20E3,0xFE0E,0xFE0F)):
                continue
            result.append(char)
        return " ".join("".join(result).split())

    @staticmethod
    def _plural_form(value: int) -> str:
        value=abs(int(value))
        if value%10==1 and value%100!=11: return "one"
        if 2<=value%10<=4 and not 12<=value%100<=14: return "few"
        return "many"

    def _text(self, key: str, **kwargs) -> str:
        return self.strings[key].format(**kwargs)

    def _plural(self, key: str, value: int, **kwargs) -> str:
        return self._text(f"{key}_{self._plural_form(value)}",count=value,**kwargs)

    def _service_duration(self, seconds) -> str:
        try: seconds=max(0,int(seconds or 0))
        except Exception: return ""
        if not seconds: return ""
        for size,unit in ((86400,"day"),(3600,"hour"),(60,"minute"),(1,"second")):
            if seconds%size==0:
                value=seconds//size
                return self._plural(f"duration_{unit}",value)
        return self._plural("duration_second",seconds)

    def _service_amount(self, action) -> str:
        stars=getattr(action,"stars",None)
        if stars is not None:
            try: return self._plural("stars",int(stars))
            except Exception: return self._text("stars_many",count=stars)
        amount=getattr(action,"total_amount",None)
        if amount is None: amount=getattr(action,"amount",None)
        currency=str(getattr(action,"currency",None) or "").upper()
        if amount is None: return currency
        try:
            numeric=int(amount)
            value=f"{numeric/100:,.2f}" if currency else f"{numeric:,}"
        except Exception:
            value=str(amount)
        return " ".join(part for part in (value,currency) if part)

    def _service_reply_slice(self, text: str, entities: List[dict], actor_name: str) -> Tuple[str,List[dict]]:
        stripped=str(text or "").strip()
        removed=0; actor=str(actor_name or "").strip()
        if actor and stripped.startswith(actor):
            before=stripped
            stripped=stripped[len(actor):].lstrip(" \t,:;\u2013\u2014-")
            removed=Dick.u16(before)-Dick.u16(stripped)

        shifted=[]
        text_len=Dick.u16(stripped)
        for entity in entities or []:
            start=int(entity.get("offset",0) or 0)
            length=int(entity.get("length",0) or 0)
            end=start+length
            if end<=removed or start>=removed+text_len: continue
            copy=dict(entity)
            copy["offset"]=max(0,start-removed)
            copy["length"]=min(end-removed,text_len)-copy["offset"]
            if copy["length"]>0: shifted.append(copy)
        if stripped:
            shifted.insert(0,{"type":"media_type","offset":0,"length":text_len})
        return stripped,shifted

    async def _service_peer_name(self, value, fallback: Optional[str]=None) -> str:
        fallback=self.strings["someone"] if fallback is None else fallback
        if value is None: return fallback
        peers=[value]
        try: peers.append(types.PeerUser(int(value)))
        except Exception: pass
        for peer in peers:
            try:
                name=telethon.utils.get_display_name(await self.client.get_entity(peer))
                if name: return name
            except Exception: pass
        return fallback

    async def _service_user_names(self, values, actor_id: int=0) -> List[str]:
        result=[]
        for value in list(values or []):
            try: raw=int(value)
            except Exception: raw=0
            result.append("" if raw and raw==actor_id else await self._service_peer_name(value))
        return result

    def _service_join_names(self, values: List[str]) -> str:
        values=[value for value in values if value]
        if not values: return self.strings["someone"]
        if len(values)==1