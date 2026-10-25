#include <stdio.h>
#define MAX_AGE 3600
#define REVOKE(s) revoke_session((s)->id)

/* Revoke one session. */
static int *revoke_session(struct session *s)
{
	db_delete(s->id);
	return NULL;
}

struct session {
	int id;
};

typedef struct {
	int timeout;
} manager_t;

#ifdef CONFIG_AUDIT
void audit(void) { log_event(1); }
#endif

int (*handler)(int) = NULL;
int prototype_only(int x);
