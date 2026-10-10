import {AbsoluteFill, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';
import {useEffect, useState} from 'react';
import type {CSSProperties} from 'react';

type Message = {from: 'me' | 'them'; text: string; status: '' | 'sent' | 'delivered' | 'read'; reaction: string};
type Bubble = {
  index: number; startFrame: number; typingStartFrame: number | null;
  reactionFrame: number | null; receiptFrame: number | null;
  lines: string[]; x: number; y: number; width: number; height: number; tail: boolean;
};
type Plan = {
  fps: number; width: number; height: number; durationInFrames: number;
  safeTop: number; safeBottom: number; fontSize: number; lineHeight: number; padding: number;
  contactFontSize?: number;
  bubbles: Bubble[]; scrollEvents: {frame: number; endFrame?: number; offset: number}[];
};
export type ChatStory = {
  payload: {
    theme: 'generic' | 'slate' | 'moss'; messages: Message[];
    contact: {name: string; avatar: 'initials' | 'placeholder'}; dramatization: boolean;
  };
  plan: Plan;
};

const palettes = {
  generic: {background: '#f3f0e9', chrome: '#ffffff', sent: '#635d86', received: '#ded9ce', text: '#242332', muted: '#657286', avatar: '#dae3f3'},
  slate: {background: '#f5f5f7', chrome: '#ffffff', sent: '#426ac3', received: '#e2e3e8', text: '#242332', muted: '#627386', avatar: '#d5deeb'},
  moss: {background: '#eef3ef', chrome: '#ffffff', sent: '#477965', received: '#dce6df', text: '#242332', muted: '#64756c', avatar: '#d7e5dc'},
};
const receipts = {sent: 'Sent', delivered: 'Delivered', read: 'Read'};
const graphemeSegmenter = new Intl.Segmenter(undefined, {granularity: 'grapheme'});
const fontPromises = new Map<string, Promise<FontFace>>();
const fontFiles = {'renderhaus-chat-text': 'DejaVuSans.ttf', 'renderhaus-chat-emoji': 'NotoColorEmoji.ttf'};
const emojiPattern = /[\u{1F000}-\u{1FAFF}\u2600-\u27FF\u203C\u2049\u20E3\u231A\u231B\u23F0\u23F3\u2B50\u2B55]/u;

export function assertChatStory(story: ChatStory): void {
  const {payload, plan} = story;
  if (!payload || !plan || !Object.hasOwn(palettes, payload.theme) ||
      !Array.isArray(payload.messages) || payload.messages.length < 1 || payload.messages.length > 40 ||
      !Array.isArray(plan.bubbles) || plan.bubbles.length !== payload.messages.length ||
      !Array.isArray(plan.scrollEvents) || !payload.contact ||
      !['initials', 'placeholder'].includes(payload.contact.avatar) ||
      typeof payload.contact.name !== 'string' || !payload.contact.name.trim()) {
    throw new Error('Chat-story props require a validated fictional message table and deterministic plan.');
  }
  for (const value of [plan.fps, plan.width, plan.height, plan.durationInFrames, plan.fontSize, plan.lineHeight, plan.padding]) {
    if (!Number.isFinite(value) || value <= 0) throw new Error('Chat-story geometry and timing must be finite and positive.');
  }
  if (plan.fps > 60 || plan.durationInFrames / plan.fps > 600 ||
      plan.safeTop < 0 || plan.safeBottom < 0 || plan.safeTop + plan.safeBottom >= plan.height) {
    throw new Error('Chat-story props exceed the supported duration or safe viewport.');
  }
  if (plan.contactFontSize !== undefined && (!Number.isFinite(plan.contactFontSize) || plan.contactFontSize <= 0)) {
    throw new Error('Chat-story contact font must use the bounded size in its validated plan.');
  }
  plan.bubbles.forEach((bubble, index) => {
    const message = payload.messages[index];
    if (!message || !['me', 'them'].includes(message.from) || typeof message.text !== 'string' ||
        !message.text.trim() || bubble.index !== index || !Array.isArray(bubble.lines) ||
        bubble.lines.some((line) => typeof line !== 'string') ||
        !Number.isInteger(bubble.startFrame) || bubble.startFrame < 0 || bubble.startFrame >= plan.durationInFrames ||
        [bubble.x, bubble.y, bubble.width, bubble.height].some((value) => !Number.isFinite(value))) {
      throw new Error('Chat-story bubbles must match the normalized message order and frame plan.');
    }
  });
}

function useChatFonts(story: ChatStory): void {
  const requiresEmoji = emojiPattern.test(story.payload.contact.name) ||
    story.payload.messages.some((message) => emojiPattern.test(message.text + message.reaction));
  const [handle] = useState(() => delayRender('Loading required chat-story fonts'));
  useEffect(() => {
    let active = true;
    const families: (keyof typeof fontFiles)[] = requiresEmoji
      ? ['renderhaus-chat-text', 'renderhaus-chat-emoji'] : ['renderhaus-chat-text'];
    const loads = families.map((family) => {
      let pending = fontPromises.get(family);
      if (!pending) {
        pending = new FontFace(family, `url("${staticFile(`fonts/${fontFiles[family]}`)}")`).load();
        fontPromises.set(family, pending);
      }
      return pending;
    });
    Promise.all(loads).then((faces) => {
      faces.forEach((face) => globalThis.document.fonts.add(face));
      if (active) continueRender(handle);
    }).catch(() => {
      if (active) cancelRender(new Error('Required chat-story text or emoji font is unavailable.'));
    });
    return () => { active = false; };
  }, [handle, requiresEmoji]);
}

function scrollOffset(plan: Plan, frame: number): number {
  let previous = 0;
  for (const event of plan.scrollEvents) {
    if (frame < event.frame) break;
    const end = event.endFrame ?? event.frame;
    if (frame < end) {
      return previous + (event.offset - previous) * (frame - event.frame) / Math.max(1, end - event.frame);
    }
    previous = event.offset;
  }
  return previous;
}

function lineDirection(line: string): 'rtl' | 'ltr' {
  for (const character of line) {
    if (/[\u0590-\u08FF]/u.test(character)) return 'rtl';
    if (/\p{Letter}/u.test(character)) return 'ltr';
  }
  return 'ltr';
}

export function ChatStoryLayer({story}: {story: ChatStory}) {
  assertChatStory(story);
  useChatFonts(story);
  const frame = useCurrentFrame();
  const {payload, plan} = story;
  const palette = palettes[payload.theme];
  const scale = plan.width / 1080;
  const floor = plan.height - plan.safeBottom;
  const scroll = scrollOffset(plan, frame);
  const headerEnd = Math.min(plan.safeTop - 12 * scale, 226 * scale);
  const tagY = headerEnd >= 200 * scale ? headerEnd - 25 * scale : 110 * scale;
  const initials = payload.contact.avatar === 'initials'
    ? payload.contact.name.split(/\s+/u).filter(Boolean).slice(0, 2)
      .map((word) => graphemeSegmenter.segment(word)[Symbol.iterator]().next().value?.segment ?? '')
      .join('').toUpperCase() : '•';
  const fontFamily = 'renderhaus-chat-text, renderhaus-chat-emoji';
  return <AbsoluteFill style={{backgroundColor: palette.background, fontFamily, color: palette.text}}>
    <div style={{position: 'absolute', inset: 0, height: headerEnd, backgroundColor: palette.chrome,
      borderBottom: `${Math.max(1, scale)}px solid ${palette.received}`}}>
      <span style={{position: 'absolute', left: 64 * scale, top: 35 * scale, fontSize: 30 * scale}}>9:41</span>
      {[0, 1, 2].map((index) => <span key={index} style={{position: 'absolute', right: (87 - index * 19) * scale,
        top: 40 * scale, width: 11 * scale, height: 17 * scale, borderRadius: 3 * scale, backgroundColor: palette.muted}}/>)}
      <div style={{position: 'absolute', left: plan.width / 2 - 34 * scale, top: 76 * scale,
        width: 68 * scale, height: 68 * scale, borderRadius: '50%', backgroundColor: palette.avatar,
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 27 * scale}}>{initials}</div>
      <div style={{position: 'absolute', top: 164 * scale, left: 48 * scale, width: plan.width - 96 * scale,
        textAlign: 'center', fontSize: plan.contactFontSize ?? 34 * scale, whiteSpace: 'nowrap'}}>{payload.contact.name}</div>
      {payload.dramatization ? <span style={{position: 'absolute', left: 48 * scale, top: tagY,
        fontSize: 21 * scale, color: palette.muted}}>Dramatization</span> : null}
    </div>
    <div style={{position: 'absolute', left: 0, top: plan.safeTop, width: plan.width,
      height: floor - plan.safeTop, overflow: 'hidden'}}>
      {plan.bubbles.map((bubble) => {
        const message = payload.messages[bubble.index];
        const sent = message.from === 'me';
        const y = bubble.y - scroll - plan.safeTop;
        if (bubble.typingStartFrame !== null && frame >= bubble.typingStartFrame && frame < bubble.startFrame) {
          const typingY = Math.min(Math.max(0, y), floor - plan.safeTop - 58 * scale);
          const phase = Math.floor(frame / Math.max(1, plan.fps * .18)) % 3;
          return <div key={bubble.index} style={{position: 'absolute', left: bubble.x, top: typingY,
            width: 124 * scale, height: 58 * scale, borderRadius: 24 * scale, backgroundColor: palette.received}}>
            {[0, 1, 2].map((index) => {
              const radius = (index === phase ? 7 : 5) * scale;
              return <span key={index} style={{position: 'absolute', left: (34 + 28 * index) * scale - radius,
                top: 29 * scale - radius, width: radius * 2, height: radius * 2,
                borderRadius: '50%', backgroundColor: palette.muted}}/>;
            })}
          </div>;
        }
        if (frame < bubble.startFrame) return null;
        const progress = Math.min(1, Math.max(0, (frame - bubble.startFrame + 1) / Math.max(1, Math.round(plan.fps * .16))));
        const fill = sent ? palette.sent : palette.received;
        const style: CSSProperties = {position: 'absolute', left: bubble.x, top: y, width: bubble.width,
          height: bubble.height, borderRadius: 26 * scale, backgroundColor: fill, opacity: progress,
          scale: .94 + .06 * (1 - Math.pow(1 - progress, 3)), transformOrigin: sent ? 'right bottom' : 'left bottom'};
        return <div key={bubble.index}>
          <div style={style}>
            {bubble.tail ? <span style={{position: 'absolute', bottom: 0, [sent ? 'right' : 'left']: -7 * scale,
              width: 30 * scale, height: 25 * scale, backgroundColor: fill,
              clipPath: sent ? 'polygon(0 0,100% 100%,0 88%)' : 'polygon(100% 0,0 100%,100% 88%)'}}/> : null}
            <div style={{position: 'absolute', left: plan.padding, top: plan.padding, width: bubble.width - 2 * plan.padding,
              color: sent ? '#ffffff' : palette.text, fontSize: plan.fontSize, lineHeight: `${plan.lineHeight}px`, whiteSpace: 'pre'}}>
              {bubble.lines.map((line, index) => <div key={index} style={{height: plan.lineHeight, direction: lineDirection(line)}}>{line}</div>)}
            </div>
          </div>
          {sent && bubble.receiptFrame !== null && frame >= bubble.receiptFrame && message.status ?
            <div style={{position: 'absolute', left: bubble.x, top: y + bubble.height + 10 * scale, width: bubble.width,
              textAlign: 'right', fontSize: 23 * scale, color: palette.muted}}>{receipts[message.status]}</div> : null}
          {bubble.reactionFrame !== null && frame >= bubble.reactionFrame && message.reaction ?
            <div style={{position: 'absolute', left: bubble.x + 8 * scale,
              top: y + bubble.height - 4 * scale, width: 70 * scale, height: 52 * scale,
              borderRadius: 24 * scale, border: `${Math.max(1, scale)}px solid ${palette.received}`,
              backgroundColor: palette.chrome, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 29 * scale}}>{message.reaction}</div> : null}
        </div>;
      })}
    </div>
    <div style={{position: 'absolute', left: '38%', bottom: 30 * scale, width: '24%', height: 8 * scale,
      borderRadius: 4 * scale, backgroundColor: palette.muted}}/>
  </AbsoluteFill>;
}
