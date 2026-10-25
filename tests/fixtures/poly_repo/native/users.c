#include "session.h"

void disable_user(struct user *u)
{
	u->active = 0;
	for (int i = 0; i < u->n_sessions; i++)
		revoke_session(u->sessions[i]);
}
