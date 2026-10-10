import {z} from 'zod';

// Python normalization is authoritative. Native validation never coerces or rewrites text.
const number = z.number().finite();
const frame = number.int().min(0).max(36000);
const text = (maximum: number) => z.string().refine(
  (value) => value.trim().length > 0 && Array.from(value).length <= maximum,
  `Expected nonempty verbatim text containing at most ${maximum} characters.`,
);
const audioReference = z.string().max(200).refine(
  (value) => !value.startsWith('-') && !value.startsWith('~') &&
    !/[:\\\u0000-\u001F]/u.test(value) && !value.split('/').includes('..'),
  'Expected a safe supplied local audio reference.',
);
const warnings = z.array(z.string().max(300)).max(50);
const message = z.object({
  from: z.enum(['me', 'them']), text: text(500),
  typingMs: number.min(0).max(10000), delayMs: number.min(0).max(30000),
  status: z.enum(['', 'sent', 'delivered', 'read']),
  reaction: z.enum(['', '❤️', '👍', '😂', '‼️', '❓']),
}).strict();
const payload = z.object({
  messages: z.array(message).min(1).max(40),
  contact: z.object({name: text(40), avatar: z.enum(['initials', 'placeholder'])}).strict(),
  theme: z.enum(['generic', 'slate', 'moss']), aspect: z.enum(['9:16', '1:1', '4:5']),
  dramatization: z.boolean(), sfx: z.boolean(), warnings,
  music_ref: audioReference, send_sound_ref: audioReference, receive_sound_ref: audioReference,
  holdMs: number.min(500).max(10000), platformTargetMs: number.min(1000).max(600000),
}).strict();
const bubble = message.extend({
  index: number.int().min(0).max(39), lines: z.array(z.string()).min(1).max(501),
  typingStartFrame: frame.nullable(), startFrame: frame,
  reactionFrame: frame.nullable(), receiptFrame: frame.nullable(),
  x: number.nonnegative(), y: number.nonnegative(), width: number.positive(), height: number.positive(),
  scrollOffset: number.nonnegative(), tail: z.boolean(),
}).strict();
const plan = z.object({
  fps: number.int().min(1).max(60), width: number.int().min(2).max(1080),
  height: number.int().min(2).max(1920), durationInFrames: frame.min(1),
  durationSeconds: number.positive().max(600), fontSize: number.positive(),
  contactFontSize: number.positive(), lineHeight: number.positive(), padding: number.positive(),
  safeTop: number.nonnegative(), safeBottom: number.nonnegative(),
  bubbles: z.array(bubble).min(1).max(40),
  scrollEvents: z.array(z.object({frame, endFrame: frame, offset: number.nonnegative()}).strict()).max(40),
  sfxCues: z.array(z.object({frame, kind: z.enum(['send', 'receive'])}).strict()).min(1).max(40),
  warnings, reviewFrames: z.array(frame).length(3),
}).strict();

export const ChatStorySchema = z.object({payload, plan}).strict();
export type ChatStory = z.infer<typeof ChatStorySchema>;
