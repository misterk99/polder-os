/* pc-drag: test helper for polder-comp. Real input via wlr-virtual-pointer:
 *   pc-drag X1 Y1 X2 Y2 [steps] [W H]
 * moves the pointer to (X1,Y1), presses the left button, glides to (X2,Y2), releases. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"
static struct zwlr_virtual_pointer_manager_v1 *mgr; static struct wl_seat *seat;
static void reg(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
	if (!strcmp(i, zwlr_virtual_pointer_manager_v1_interface.name)) mgr = wl_registry_bind(r, n, &zwlr_virtual_pointer_manager_v1_interface, 1);
	else if (!strcmp(i, wl_seat_interface.name)) seat = wl_registry_bind(r, n, &wl_seat_interface, 1);
}
static void unreg(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener rl = { reg, unreg };
static uint32_t t = 1;
static void mv(struct wl_display *dpy, struct zwlr_virtual_pointer_v1 *p, int x, int y, int W, int H) {
	zwlr_virtual_pointer_v1_motion_absolute(p, t++, x, y, W, H); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(dpy); usleep(15000);
}
int main(int argc, char **argv) {
	if (argc < 5) { fprintf(stderr, "usage: pc-drag X1 Y1 X2 Y2 [steps] [W H]\n"); return 1; }
	uint32_t btn = getenv("PC_BUTTON") ? strtoul(getenv("PC_BUTTON"), NULL, 0) : 0x110;   /* 0x111 = right */
	int x1 = atoi(argv[1]), y1 = atoi(argv[2]), x2 = atoi(argv[3]), y2 = atoi(argv[4]);
	int steps = argc > 5 ? atoi(argv[5]) : 20, W = argc > 7 ? atoi(argv[6]) : 1366, H = argc > 7 ? atoi(argv[7]) : 768;
	struct wl_display *dpy = wl_display_connect(NULL); if (!dpy) { perror("connect"); return 1; }
	struct wl_registry *r = wl_display_get_registry(dpy); wl_registry_add_listener(r, &rl, NULL); wl_display_roundtrip(dpy);
	if (!mgr) { fprintf(stderr, "no virtual pointer manager\n"); return 1; }
	struct zwlr_virtual_pointer_v1 *p = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(mgr, seat);
	mv(dpy, p, x1, y1, W, H);
	zwlr_virtual_pointer_v1_button(p, t++, btn, 1); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(dpy); usleep(50000);
	for (int i = 1; i <= steps; i++) mv(dpy, p, x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps, W, H);
	zwlr_virtual_pointer_v1_button(p, t++, btn, 0); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(dpy);
	zwlr_virtual_pointer_v1_destroy(p); wl_display_roundtrip(dpy); wl_display_disconnect(dpy); return 0;
}
