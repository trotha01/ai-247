// Fixed link to the Puddle Park showrunner studio. The GPU box runs it behind a Cloudflare quick tunnel whose address
// changes on every restart; the box writes the current address to R2 (puddle/showrunner/url.txt) and this Worker forwards to it.
export default {
  async fetch(request, env) {
    const obj = await env.BUCKET.get("puddle/showrunner/url.txt");
    const url = obj ? (await obj.text()).trim() : "";
    if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(url)) {
      return new Response("The showrunner is offline right now. Try again in a few minutes.", {
        status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
    }
    return Response.redirect(url + "/", 302);
  },
};
