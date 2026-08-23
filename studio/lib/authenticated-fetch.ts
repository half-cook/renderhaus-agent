type TokenGetter = () => Promise<string | null>;

let tokenGetter: TokenGetter = async () => null;

export function configureStudioTokenGetter(next: TokenGetter): void {
  tokenGetter = next;
}

export async function studioFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const token = await tokenGetter();
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}
