/* Synthetic Xlib ordering/boundary tests, not guest frame acceptance. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned long Xid;
typedef struct {int type;unsigned long serial;int send_event;void *display;Xid event,window;} Event;
extern void _ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent(void *,const Event *);
extern void _ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent(void *,const Event *);
extern void _ZN24MCompositeManagerPrivate12destroyEventEP19XDestroyWindowEvent(void *,const Event *);
extern void XCompositeUnredirectWindow(void *,Xid,int);
static int mode,display,manager,other_display,original_maps,original_unmaps,original_destroys,unredirects;
static int preserved,restored,background_none,cleared,shared,pending,allocated,freed,gc,copy_order;
static Xid background_pixmap;
static unsigned captured_pixel,screen_pixel=42,parent_pixel=77;
static Xid prop_value;
static Xid root(void *d){assert(d==&display);return 10;}
static Xid atom(void *d,const char *name,int only){
    assert(d==&display&&!only);
    if(!strcmp(name,"_NET_WM_WINDOW_TYPE"))return 200;
    if(!strcmp(name,"_NET_WM_WINDOW_TYPE_INPUT"))return 201;
    assert(!strcmp(name,"_NET_ACTIVE_WINDOW"));return 202;
}
static int property(void *d,Xid w,Xid a,long offset,long length,int del,Xid req,
                    Xid *actual,int *format,unsigned long *count,unsigned long *after,unsigned char **data){
    assert(d==&display&&!offset&&length==1&&!del);
    assert((w==30&&a==200&&req==4)||(w==10&&a==202&&req==33));
    *actual=req;*format=mode==9?16:32;*count=1;*after=0;
    prop_value=w==30?(mode==1?205:201):(mode==2?21:20);
    *data=(unsigned char *)&prop_value;return 0;
}
static int free_data(void *p){assert(p==&prop_value);return 1;}
static int transient(void *d,Xid w,Xid *p){assert(d==&display&&w==30);*p=20;return mode!=5;}
static int geometry(void *d,Xid w,Xid *r,int *x,int *y,unsigned *width,unsigned *height,unsigned *border,unsigned *depth){
    /* IM geometry is intentionally not queried before the original manager
     * maps/resizes its initial 432x192 window. */
    assert(d==&display&&(w==10||w==20||w==200));
    *r=10;*x=*y=0;*border=0;*width=mode==3?640:864;*height=480;*depth=mode==4?32:24;return !(mode==14&&w==200);
}
static int set_pixmap(void *d,Xid w,Xid p){
    assert(d==&display&&w==10);
    if(p==100){assert(!background_none&&captured_pixel==screen_pixel);background_none=1;}
    else {assert(p==200&&background_none&&background_pixmap==100&&parent_pixel==77);}
    background_pixmap=p;return 1;
}
static Xid create_pixmap(void *d,Xid w,unsigned width,unsigned height,unsigned depth){
    assert(d==&display&&w==10&&width==864&&height==480&&depth==24&&!allocated);allocated=1;return 100;
}
static void *create_gc(void *d,Xid w,unsigned long mask,void *values){assert(d==&display&&w==10&&!mask&&!values);copy_order=0;return &gc;}
static int subwindows(void *d,void *g,int value){assert(d==&display&&g==&gc&&value==1&&copy_order++==0);return 1;}
static int exposures(void *d,void *g,int value){assert(d==&display&&g==&gc&&!value&&copy_order++==1);return 1;}
static int copy(void *d,Xid src,Xid dst,void *g,int x,int y,unsigned w,unsigned h,int dx,int dy){
    assert(d==&display&&src==10&&dst==100&&g==&gc&&!x&&!y&&!dx&&!dy&&w==864&&h==480&&copy_order++==2);
    captured_pixel=screen_pixel;return 1;
}
static int free_gc(void *d,void *g){assert(d==&display&&g==&gc&&copy_order++==3);return 1;}
static Xid name_pixmap(void *d,Xid window){assert(d==&display&&window==20&&original_maps==1);return 200;}
static int free_pixmap(void *d,Xid p){
    assert(d==&display);
    if(p==100){assert(allocated&&(background_pixmap==200||(mode==14&&!background_pixmap)));allocated=0;}
    else {assert(p==200&&((!background_none&&!background_pixmap&&!allocated)||(mode==14&&background_pixmap==100)));}
    ++freed;return 1;
}
static int screen(void *d){assert(d==&display);return 0;}
static Xid black(void *d,int s){assert(d==&display&&!s);return 0;}
static int set_black(void *d,Xid w,Xid p){assert(d==&display&&w==10&&!p&&background_none);background_none=0;background_pixmap=0;return 1;}
static int clear(void *d,Xid w){assert(d==&display&&w==10&&!background_none);++cleared;return 1;}
static void map(void *self,const Event *e){
    assert(self==&manager&&e->window==30);++original_maps;
    if(mode==0||mode>=8){if(mode!=9)assert(background_none);}
    if(background_none&&original_maps==1)assert(background_pixmap==100&&captured_pixel==42);
}
static void unmap(void *self,const Event *e){assert(self==&manager&&e);++original_unmaps;}
static void destroy(void *self,const Event *e){assert(self==&manager&&e);++original_destroys;}
static void unredirect(void *d,Xid w,int update){
    assert((d==&display||d==&other_display)&&(w==20||w==30)&&(update==0||update==1));
    assert(background_none);++unredirects;
}
void *dlsym(void *handle,const char *name){
    assert(handle==(void *)-1);
    if(mode==7&&!strcmp(name,"XSetWindowBackgroundPixmap"))return 0;
#define SYM(n,f) if(!strcmp(name,n))return f
    SYM("XDefaultRootWindow",root);SYM("XInternAtom",atom);SYM("XGetWindowProperty",property);SYM("XFree",free_data);
    SYM("XGetTransientForHint",transient);SYM("XGetGeometry",geometry);SYM("XSetWindowBackgroundPixmap",set_pixmap);
    SYM("XSetWindowBackground",set_black);SYM("XBlackPixel",black);SYM("XDefaultScreen",screen);SYM("XClearWindow",clear);
    SYM("XCreatePixmap",create_pixmap);SYM("XCreateGC",create_gc);SYM("XSetSubwindowMode",subwindows);
    SYM("XSetGraphicsExposures",exposures);SYM("XCopyArea",copy);SYM("XFreeGC",free_gc);
    SYM("XCompositeNameWindowPixmap",name_pixmap);SYM("XFreePixmap",free_pixmap);
    SYM("_ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent",map);
    SYM("_ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent",unmap);
    SYM("_ZN24MCompositeManagerPrivate12destroyEventEP19XDestroyWindowEvent",destroy);
    SYM("XCompositeUnredirectWindow",unredirect);
#undef SYM
    assert(0);return 0;
}
int write(int fd,const void *message,unsigned size){
    assert(size&&message&&(fd==1||fd==2));
    if(fd==2){assert(strstr(message,"INPUT_HANDOFF_ERROR"));return (int)size;}
    if(strstr(message,"PRESERVED")){assert(background_none&&!restored&&background_pixmap==100);++preserved;}
    else if(strstr(message,"SHARED")){assert(background_none&&background_pixmap==200&&!allocated);++shared;}
    else if(strstr(message,"PENDING")){assert(mode==14&&background_pixmap==100&&allocated);++pending;}
    else {assert(strstr(message,"RESTORED")&&!background_none);++restored;}
    return (int)size;
}
void _exit(int code){exit(code);}
int main(int argc,char **argv){
    assert(argc==2);mode=atoi(argv[1]);
    Event e={20,1,0,&display,mode==6?11:10,30};
    _ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent(&manager,&e);
    assert(original_maps==1);
    if((mode>=1&&mode<=6)||mode==9){assert(!preserved&&!restored&&!background_none);return 0;}
    assert(preserved==1&&!restored&&background_none);
    if(mode==8){_ZN24MCompositeManagerPrivate15mapRequestEventEP16XMapRequestEvent(&manager,&e);assert(preserved==1&&original_maps==2);}
    XCompositeUnredirectWindow(&display,30,1);assert(background_none);
    XCompositeUnredirectWindow(&display,20,0);assert(background_none);
    if(mode==13){XCompositeUnredirectWindow(&other_display,20,1);assert(background_none);}
    Event gone={18,1,0,&display,10,21};
    _ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent(&manager,&gone);assert(background_none&&original_unmaps==1);
    gone.window=20;
    if(mode==12){gone.send_event=1;_ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent(&manager,&gone);assert(background_none);}
    if(mode==10)_ZN24MCompositeManagerPrivate10unmapEventEP11XUnmapEvent(&manager,&gone);
    else if(mode==11)_ZN24MCompositeManagerPrivate12destroyEventEP19XDestroyWindowEvent(&manager,&gone);
    else XCompositeUnredirectWindow(&display,20,1);
    assert(restored==1&&!background_none&&preserved==1);
    assert(shared==(mode==14?0:1)&&pending==(mode==14?1:0)&&freed==2&&!allocated);
    assert(cleared==((mode==10||mode==11)?1:0));
    return 0;
}
