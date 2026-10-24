#include "session.h"

/* Remove one session from the table. */
void revoke_session(int id)
{
	store_delete(id);
}
