/* Exercise the actual static function extracted from patched valid.c. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <libxml/tree.h>
#include <libxml/parser.h>
#include "xml-elements-under-test.inc"

int main(void) {
    xmlNodePtr node = xmlNewNode(NULL, BAD_CAST "child");
    assert(node != NULL);
    for (int size = 64; size <= 256; size++) {
        for (int len = 1; len < size; len++) {
            for (int glob = 0; glob <= 1; glob++) {
                char *buf = malloc((size_t)size + 32);
                assert(buf != NULL);
                memset(buf, 0x5a, (size_t)size + 32);
                memset(buf, 'x', (size_t)len);
                buf[len] = '\0';
                xmlSnprintfElements(buf, size, node, glob);
                assert(strlen(buf) < (size_t)size);
                for (int i = size; i < size + 32; i++) assert(buf[i] == 0x5a);
                free(buf);
            }
        }
    }
    xmlFreeNode(node);
    xmlCleanupParser();
    return 0;
}
