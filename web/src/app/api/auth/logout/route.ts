import { NextResponse } from 'next/server';
import { agentCookie, cookieOptions, sessionCookie } from '@/lib/session';

export async function POST(request: Request) {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(sessionCookie, '', { ...cookieOptions(request), maxAge: 0 });
  response.cookies.set(agentCookie, '', { ...cookieOptions(request), maxAge: 0 });
  return response;
}
