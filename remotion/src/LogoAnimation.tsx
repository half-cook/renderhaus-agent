import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {z} from 'zod';

const coordinate = z.number().finite().min(0).max(2048);
const partSchema = z.object({
  id: z.string().regex(/^[a-z][a-z0-9-]{0,39}$/),
  fill: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  kind: z.enum(['rect', 'ellipse', 'path']), d: z.string().max(60000),
  loops: z.array(z.array(z.tuple([coordinate, coordinate])).min(3).max(4096)).min(1).max(128),
});
const rowSchema = z.object({
  part: z.string(), start_ms: z.number().finite().min(0).max(3000),
  end_ms: z.number().finite().min(0).max(3000), easing: z.enum(['settle', 'enter']),
  paint: z.literal('fill'), draw_order: z.number().int().min(0).max(31),
}).refine((row) => row.end_ms > row.start_ms, 'Motion window must advance.');
export const logoPlanSchema = z.object({
  name: z.literal('logo-animation'), duration_seconds: z.number().min(1).max(3),
  fps: z.number().int().min(12).max(60), width: z.number().int().min(2).max(2048),
  height: z.number().int().min(2).max(2048), background_color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  geometry: z.object({width: coordinate.min(1), height: coordinate.min(1),
    parts: z.array(partSchema).min(1).max(32)}),
  motion_spec: z.object({style: z.enum(['reveal', 'splash', 'loader', 'idle-hover']),
    timeline: z.array(rowSchema).min(1).max(32),
    source_width: coordinate.min(1), source_height: coordinate.min(1)}),
}).refine((plan) => plan.geometry.parts.length === plan.motion_spec.timeline.length
  && plan.geometry.parts.every((part, index) => part.id === plan.motion_spec.timeline[index]?.part),
'Logo parts must match the declared timeline.');
export type LogoTemplatePlan = z.infer<typeof logoPlanSchema>;

export function LogoAnimation({plan: input}: {plan: LogoTemplatePlan}) {
  const frame = useCurrentFrame();
  const plan = logoPlanSchema.parse(input);
  const {geometry, motion_spec: spec} = plan;
  const fit = Math.min(plan.width / geometry.width, plan.height / geometry.height) * 0.7;
  const width = Math.max(1, Math.round(geometry.width * fit));
  const height = Math.max(1, Math.round(geometry.height * fit));
  return <AbsoluteFill style={{backgroundColor: plan.background_color}}>
    <svg xmlns="http://www.w3.org/2000/svg" width={width} height={height}
      style={{position: 'absolute', left: Math.floor((plan.width - width) / 2), top: Math.floor((plan.height - height) / 2)}}
      viewBox={`0 0 ${geometry.width} ${geometry.height}`}>
      {geometry.parts.map((part, index) => {
        const row = spec.timeline[index];
        if (!row) throw new Error('Logo timeline is incomplete.');
        const t = Math.min(1, Math.max(0, (frame / plan.fps * 1000 - row.start_ms) / (row.end_ms - row.start_ms)));
        const p = row.easing === 'settle' ? t * t * (3 - 2 * t) : 1 - (1 - t) ** 3;
        const loader = spec.style === 'loader';
        const initial = spec.style === 'splash' ? 0.72 : 0.96;
        const scale = t === 1 ? 1 : loader ? 1 + 0.025 * Math.sin(p * Math.PI * 2) ** 2 : initial + (1 - initial) * p;
        const opacity = t === 1 || loader ? 1 : p;
        const y = t === 1 || loader || spec.style === 'splash' ? 0 : (1 - p) * spec.source_height * 0.035;
        const path = part.kind === 'path' ? part.d : part.loops.map((loop) =>
          loop.map(([x, py], i) => `${i ? 'L' : 'M'} ${x} ${py}`).join(' ') + ' Z').join(' ');
        return <g key={part.id} id={part.id} opacity={opacity}
          transform={`translate(${geometry.width / 2} ${geometry.height / 2 + y}) scale(${scale}) translate(${-geometry.width / 2} ${-geometry.height / 2})`}>
          <path d={path} fill={part.fill} fillRule="evenodd"/>
        </g>;
      })}
    </svg>
  </AbsoluteFill>;
}
