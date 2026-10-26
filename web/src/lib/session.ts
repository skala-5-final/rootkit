import { SignJWT, jwtVerify } from 'jose';

export const sessionCookie = 'rootkit_session';
export const sessionMaxAge = 60 * 60 * 24 * 7;
export type Session = { userId: string; loginId: string; name: string };

function secret() {
  const value = process.env.JWT_SECRET;
  if (!value || value.length < 32) throw new Error('JWT_SECRET 환경변수를 32자 이상으로 설정해 주세요.');
  return new TextEncoder().encode(value);
}
export function signSession(session: Session) {
  return new SignJWT({ loginId: session.loginId, name: session.name }).setProtectedHeader({ alg: 'HS256' }).setSubject(session.userId).setIssuedAt().setExpirationTime(`${sessionMaxAge}s`).sign(secret());
}
export async function verifySession(token: string | undefined): Promise<Session | null> {
  if (!token) return null;
  const key = secret();
  try {
    const { payload } = await jwtVerify(token, key, { algorithms: ['HS256'] });
    if (typeof payload.sub !== 'string' || typeof payload.loginId !== 'string') return null;
    return { userId: payload.sub, loginId: payload.loginId, name: typeof payload.name === 'string' ? payload.name : payload.loginId };
  } catch { return null; }
}
export function cookieOptions(request: Request) {
  const https = new URL(request.url).protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
  return { httpOnly: true, sameSite: 'lax' as const, secure: https, path: '/', maxAge: sessionMaxAge };
}

export const agentCookie = 'rootkit_agent';
export function signAgentToken(token: string, userId: string) {
  return new SignJWT({ token }).setProtectedHeader({ alg: 'HS256' }).setSubject(userId)
    .setAudience('rookit-agent').setIssuedAt().setExpirationTime(`${sessionMaxAge}s`).sign(secret());
}
export async function readAgentToken(value: string | undefined, userId: string): Promise<string | null> {
  if (!value) return null;
  try {
    const { payload } = await jwtVerify(value, secret(), { algorithms: ['HS256'], audience: 'rookit-agent' });
    return payload.sub === userId && typeof payload.token === 'string' ? payload.token : null;
  } catch { return null; }
}
