import { NextResponse, type NextRequest } from 'next/server';
import { sessionCookie, verifySession } from '@/lib/session';

export async function proxy(request: NextRequest) {
  const session = await verifySession(request.cookies.get(sessionCookie)?.value);
  const { pathname } = request.nextUrl;
  if (pathname.startsWith('/api/')) {
    return session ? NextResponse.next() : Response.json({ error: '로그인이 필요합니다.' }, { status: 401 });
  }
  if (pathname === '/login') return session ? NextResponse.redirect(new URL('/kits', request.url)) : NextResponse.next();
  return session ? NextResponse.next() : NextResponse.redirect(new URL('/login', request.url));
}

export const config = {
  matcher: ['/login', '/kits', '/learn/:path*', '/history', '/documents', '/api/demo/:path*', '/api/rag/:path*', '/api/agent/:path*', '/api/auth/me'],
};
