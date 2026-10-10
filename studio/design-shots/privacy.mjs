const EMAIL = /[\w.+-]+@(?!example\.(com|org)\b)[\w-]+(\.[\w-]+)+/i;
const SECRET_URL = /X-Amz-Signature|[?&](Signature|token|sig|access_token)=|sk_(live|test)_|pk_live_/i;

export function assertCapturePrivacy(text, urls) {
  if (EMAIL.test(text)) throw new Error("Private-looking email in capture");
  if (urls.some((url) => SECRET_URL.test(url))) throw new Error("Private or signed URL in capture");
}
