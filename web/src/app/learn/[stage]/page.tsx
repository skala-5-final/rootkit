import { notFound } from 'next/navigation';
import Rootkit from '@/components/rootkit';
import { isLang, isStage, parseSessionConfig } from '@/lib/learning';
export function generateStaticParams() { return ['0', '1', '2'].map(stage => ({ stage })); }
export default async function Page({ params, searchParams }: { params: Promise<{ stage: string }>; searchParams: Promise<{ count?: string | string[]; type?: string | string[]; attempt?: string | string[]; lang?: string | string[] }> }) {
  const { stage: value } = await params;
  if (!/^[012]$/.test(value)) notFound();
  const stage = Number(value);
  if (!isStage(stage)) notFound();
  const query = await searchParams;
  const config = parseSessionConfig(query);
  const attempt = typeof query.attempt === 'string' && /^[a-zA-Z0-9_-]{1,200}$/.test(query.attempt) ? query.attempt : undefined;
  const lang = isLang(query.lang) ? query.lang : 'ko';
  return <Rootkit key={`${stage}-${lang}`} screen="learn" stage={stage} config={config} resumeAttemptId={attempt} lang={lang} />;
}
