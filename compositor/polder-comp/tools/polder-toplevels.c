/* polder-toplevels: tiny wlr-foreign-toplevel-management client for the Polder shelf (Rev 33).
 * stdout: one JSON object per line on every state change:
 *   {"ev":"state","id":N,"title":"..","app_id":"..","activated":true,"minimized":false}
 *   {"ev":"closed","id":N}
 * stdin: "activate N" | "close N" | "minimize N" | "unminimize N"  (one per line) */
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "ftl-client.h"
struct tl { struct zwlr_foreign_toplevel_handle_v1 *h; int id; char *title, *app_id; int act, min, pact, pmin; struct tl *next; };
static struct zwlr_foreign_toplevel_manager_v1 *mgr; static struct wl_seat *seat; static struct tl *list; static int next_id = 1;
static void jstr(const char *s) {
	putchar('"');
	for (; s && *s; s++) { unsigned char c = *s; if (c == '"' || c == '\\') printf("\\%c", c); else if (c < 0x20) printf("\\u%04x", c); else putchar(c); }
	putchar('"');
}
static void h_title(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, const char *t) { struct tl *x = d; free(x->title); x->title = strdup(t); }
static void h_app(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, const char *t) { struct tl *x = d; free(x->app_id); x->app_id = strdup(t); }
static void h_oe(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_output *o) {}
static void h_ol(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_output *o) {}
static void h_state(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_array *st) {
	struct tl *x = d; x->pact = x->pmin = 0; uint32_t *s;
	wl_array_for_each(s, st) { if (*s == ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_ACTIVATED) x->pact = 1; if (*s == ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_MINIMIZED) x->pmin = 1; }
}
static void h_done(void *d, struct zwlr_foreign_toplevel_handle_v1 *h) {
	struct tl *x = d; x->act = x->pact; x->min = x->pmin;
	printf("{\"ev\":\"state\",\"id\":%d,\"title\":", x->id); jstr(x->title); printf(",\"app_id\":"); jstr(x->app_id);
	printf(",\"activated\":%s,\"minimized\":%s}\n", x->act ? "true" : "false", x->min ? "true" : "false"); fflush(stdout);
}
static void h_closed(void *d, struct zwlr_foreign_toplevel_handle_v1 *h) {
	struct tl *x = d, **pp; printf("{\"ev\":\"closed\",\"id\":%d}\n", x->id); fflush(stdout);
	for (pp = &list; *pp; pp = &(*pp)->next) if (*pp == x) { *pp = x->next; break; }
	zwlr_foreign_toplevel_handle_v1_destroy(h); free(x->title); free(x->app_id); free(x);
}
static void h_parent(void *d, struct zwlr_foreign_toplevel_handle_v1 *h, struct zwlr_foreign_toplevel_handle_v1 *p) {}
static const struct zwlr_foreign_toplevel_handle_v1_listener hl = { h_title, h_app, h_oe, h_ol, h_state, h_done, h_closed, h_parent };
static void m_toplevel(void *d, struct zwlr_foreign_toplevel_manager_v1 *m, struct zwlr_foreign_toplevel_handle_v1 *h) {
	struct tl *x = calloc(1, sizeof *x); x->h = h; x->id = next_id++; x->next = list; list = x;
	zwlr_foreign_toplevel_handle_v1_add_listener(h, &hl, x);
}
static void m_finished(void *d, struct zwlr_foreign_toplevel_manager_v1 *m) { exit(0); }
static const struct zwlr_foreign_toplevel_manager_v1_listener ml = { m_toplevel, m_finished };
static void reg(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
	if (!strcmp(i, zwlr_foreign_toplevel_manager_v1_interface.name)) { mgr = wl_registry_bind(r, n, &zwlr_foreign_toplevel_manager_v1_interface, v < 3 ? v : 3); zwlr_foreign_toplevel_manager_v1_add_listener(mgr, &ml, NULL); }
	else if (!strcmp(i, wl_seat_interface.name) && !seat) seat = wl_registry_bind(r, n, &wl_seat_interface, 1);
}
static void unreg(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener rl = { reg, unreg };
static void command(char *line) {
	char cmd[32]; int id; if (sscanf(line, "%31s %d", cmd, &id) != 2) return;
	for (struct tl *x = list; x; x = x->next) if (x->id == id) {
		if (!strcmp(cmd, "activate")) zwlr_foreign_toplevel_handle_v1_activate(x->h, seat);
		else if (!strcmp(cmd, "close")) zwlr_foreign_toplevel_handle_v1_close(x->h);
		else if (!strcmp(cmd, "minimize")) zwlr_foreign_toplevel_handle_v1_set_minimized(x->h);
		else if (!strcmp(cmd, "unminimize")) zwlr_foreign_toplevel_handle_v1_unset_minimized(x->h);
	}
}
int main(void) {
	struct wl_display *dpy = wl_display_connect(NULL); if (!dpy) { fprintf(stderr, "no wayland display\n"); return 1; }
	struct wl_registry *r = wl_display_get_registry(dpy); wl_registry_add_listener(r, &rl, NULL); wl_display_roundtrip(dpy);
	if (!mgr) { fprintf(stderr, "compositor has no wlr-foreign-toplevel-management\n"); return 2; }
	wl_display_roundtrip(dpy); printf("{\"ev\":\"ready\"}\n"); fflush(stdout);
	char buf[4096]; size_t used = 0;
	for (;;) {
		while (wl_display_prepare_read(dpy) != 0) wl_display_dispatch_pending(dpy);
		wl_display_flush(dpy);
		struct pollfd p[2] = { { wl_display_get_fd(dpy), POLLIN, 0 }, { 0, POLLIN, 0 } };
		if (poll(p, 2, -1) < 0) { wl_display_cancel_read(dpy); continue; }
		if (p[0].revents & POLLIN) wl_display_read_events(dpy); else wl_display_cancel_read(dpy);
		wl_display_dispatch_pending(dpy);
		if (p[0].revents & (POLLERR | POLLHUP)) return 0;
		if (p[1].revents & (POLLIN | POLLHUP)) {
			ssize_t n = read(0, buf + used, sizeof buf - used - 1); if (n <= 0) return 0; used += n; buf[used] = 0;
			char *nl; while ((nl = strchr(buf, '\n'))) { *nl = 0; command(buf); memmove(buf, nl + 1, used - (nl + 1 - buf) + 1); used -= nl + 1 - buf; }
			wl_display_flush(dpy);
		}
	}
}
