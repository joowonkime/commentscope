export interface Statistics {comment_count:number;comment_share:number;like_count:number;like_share:number}
export interface SourceComment {comment_id:string;text:string;original_text:string;like_count:number;is_reply:boolean;url:string;translation_pending?:boolean}
export interface Agent {agent_id:string;title:string;subtitle:string;stance:string;reasoning:string;full_stance:string;statistics:Statistics;arguments:{text:string;comment_ids:string[]}[];variations:{text:string;comment_ids:string[]}[];limitations:string[];representative_comments:SourceComment[]}
export interface Message {message_id:string;role:'user'|'agent';sender_id:string;reply_to:string|null;text:string;created_at:string;segments:{text:string;basis:'comment'|'reasoning'|'uncertain';comment_ids:string[]}[];evidence:SourceComment[];follow_up_questions:string[];language?:'ko'|'en'}
export interface RoomSummary {room_id:string;title:string;participants:string[];initial_opinion:string;created_at:string;updated_at:string;paused:boolean;active_job:string|null;message_count:number;preview:string;auto_turns:number;auto_limit:number}
export interface Room extends RoomSummary {messages:Message[];errors:{agent_id:string;target_message_id:string;error:string}[]}
export interface Catalog {account_storage?:boolean;profile?:{initial_opinion?:string;saved_evidence?:import('./ChatView').SavedEvidence[]};fingerprint:string;video:{video_id:string;title:string;url:string};agents:Agent[];counts:{collected:number;keep:number;exclude:number;review:number;grouped:number;other:number;likes:number};other_statistics:Statistics;rooms:RoomSummary[]}
export interface Alignment {agent_id:string;score:number;reason:string;novelty:number;new_point:string}
export type ReflectionCategory='stayed'|'changed'|'new'|'open';
export interface ReflectionItem {category:ReflectionCategory;title:string;explanation:string;before_quote:string;now_quote:string;moment:{room_id:string;message_id:string;speaker:string;room_type:string;quote:string;user_quote:string}|null}
export interface ReflectionAnalysis {before_excerpt:string;after_excerpt:string;items:ReflectionItem[];one_to_one:number;group:number}
export type Stage='start'|'explore'|'converse'|'reflect';
export interface Comparison {similar:string;different:string;consideration:string;similar_quotes:string[];different_quotes:string[]}
export interface Job<T=unknown> {job_id:string;status:'running'|'completed'|'failed';room_id?:string;result?:T;error?:string}
export const appearance:Record<string,{color:string;avatar:string;dot:string;order:number}>={
  g4:{color:'#e8774a',avatar:'character.svg',dot:'dot.svg',order:0},
  g5:{color:'#d64f6b',avatar:'character1.svg',dot:'dot1.svg',order:1},
  g2:{color:'#6554e8',avatar:'character2.svg',dot:'dot2.svg',order:2},
  g3:{color:'#1f9e8a',avatar:'character3.svg',dot:'dot3.svg',order:3},
  g1:{color:'#3b82f6',avatar:'character4.svg',dot:'dot4.svg',order:4},
};
export const visual=(id:string)=>appearance[id]??{color:'#6554e8',avatar:'character2.svg',dot:'dot2.svg',order:5};
export const ordered=(agents:Agent[])=>[...agents].sort((a,b)=>visual(a.agent_id).order-visual(b.agent_id).order);
export const percent=(fraction:number)=>`${Math.round(fraction*100)}%`;
export const number=(value:number)=>new Intl.NumberFormat('en-US').format(value);
export const compact=(value:number)=>new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(value);
export const alignmentLabel=(score:number)=>score>=80?'Very similar':score>=60?'Similar':score>=40?'Mixed':score>=20?'Different':'Very different';
export const alignmentTone=(score:number)=>score>=60?'similar':score>=40?'mixed':'different';
