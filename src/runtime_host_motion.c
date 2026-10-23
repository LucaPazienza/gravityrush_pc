/* Motion sensors of the PC itself through the Windows Sensor API (gr_host_motion.h).
 *
 * SDL3 also lists them (SDL_GetSensors), but leaves the driver's report interval alone: on the
 * ROG Xbox Ally X (Bosch BMI323, "Sensor BMI320 Gyr") that is 100 ms, 10 gyro readings a second.
 * Here the sensors are opened directly and asked for 10 ms and no change sensitivity, which gives
 * about 60 readings a second (Windows' 15.6 ms tick). The driver still reports nothing while the
 * device is held still, so a small reading that has not changed for a while is taken as zero.
 *
 * Axes: Windows reports X right, Y to the top of the screen and Z out of the screen, angular
 * velocity in degrees/s (right-handed) and acceleration in g with gravity as -1 g upwards
 * (checked on the Ally against recordings: the integrated gyro matches the accelerometer on the
 * same axes). SDL's gamepad axes are X right, Y out of the top face and Z towards the player;
 * a handheld is a gamepad whose top face is the screen, so pad = (x, z, -y), and the
 * acceleration changes sign. GOW3_HOST_MOTION=0 turns this off. */
#include "gr_host_motion.h"
#ifdef _WIN32
#define COBJMACROS
#include <windows.h>
#include <initguid.h>
#include <sensorsapi.h>
#include <sensors.h>
#include <portabledevicetypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { KIND_GYRO, KIND_ACCEL };
static SRWLOCK lock=SRWLOCK_INIT;
static struct { double v[3]; LONGLONG at; int seen; } data[2]; /* Windows axes and units */
static INIT_ONCE started=INIT_ONCE_STATIC_INIT;
static volatile LONG ready; /* 1 gyro open, -1 none */
static char description[160];
static LARGE_INTEGER qpf;

typedef struct { ISensorEvents iface; int kind; } Sink;
static HRESULT STDMETHODCALLTYPE sink_query(ISensorEvents *self, REFIID riid, void **out) {
    if (IsEqualIID(riid,&IID_IUnknown) || IsEqualIID(riid,&IID_ISensorEvents)) { *out=self; return S_OK; }
    *out=NULL; return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE sink_ref(ISensorEvents *self) { (void)self; return 1; } /* static objects */
static HRESULT STDMETHODCALLTYPE sink_state(ISensorEvents *self, ISensor *sensor, SensorState state) {
    (void)self; (void)sensor; (void)state; return S_OK;
}
static HRESULT STDMETHODCALLTYPE sink_event(ISensorEvents *self, ISensor *sensor, REFGUID id, IPortableDeviceValues *values) {
    (void)self; (void)sensor; (void)id; (void)values; return S_OK;
}
static HRESULT STDMETHODCALLTYPE sink_leave(ISensorEvents *self, REFSENSOR_ID id) { (void)self; (void)id; return S_OK; }
static const PROPERTYKEY *const fields[2][3]={
    {&SENSOR_DATA_TYPE_ANGULAR_VELOCITY_X_DEGREES_PER_SECOND,&SENSOR_DATA_TYPE_ANGULAR_VELOCITY_Y_DEGREES_PER_SECOND,
     &SENSOR_DATA_TYPE_ANGULAR_VELOCITY_Z_DEGREES_PER_SECOND},
    {&SENSOR_DATA_TYPE_ACCELERATION_X_G,&SENSOR_DATA_TYPE_ACCELERATION_Y_G,&SENSOR_DATA_TYPE_ACCELERATION_Z_G},
};
/* Called on a COM thread (multithreaded apartment). */
static HRESULT STDMETHODCALLTYPE sink_data(ISensorEvents *self, ISensor *sensor, ISensorDataReport *report) {
    (void)sensor;
    const int kind=((Sink *)self)->kind;
    double v[3];
    for (int i=0;i<3;++i) {
        PROPVARIANT p; PropVariantInit(&p);
        const HRESULT hr=ISensorDataReport_GetSensorValue(report,fields[kind][i],&p);
        const int ok=SUCCEEDED(hr) && p.vt==VT_R8;
        if (ok) v[i]=p.dblVal;
        PropVariantClear(&p);
        if (!ok) return S_OK;
    }
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    AcquireSRWLockExclusive(&lock);
    memcpy(data[kind].v,v,sizeof v); data[kind].at=now.QuadPart; data[kind].seen=1;
    ReleaseSRWLockExclusive(&lock);
    return S_OK;
}
static ISensorEventsVtbl sink_vtbl={sink_query,sink_ref,sink_ref,sink_state,sink_data,sink_event,sink_leave};
static Sink sinks[2]={{{&sink_vtbl},KIND_GYRO},{{&sink_vtbl},KIND_ACCEL}};

static IPortableDeviceValues *new_values(void) {
    IPortableDeviceValues *v=NULL;
    CoCreateInstance(&CLSID_PortableDeviceValues,NULL,CLSCTX_INPROC_SERVER,&IID_IPortableDeviceValues,(void **)&v);
    return v;
}
/* Report interval (ms) and change sensitivity 0 for each field; the driver may round them. */
static void configure(ISensor *sensor, int kind, ULONG interval) {
    IPortableDeviceValues *in=new_values(), *sensitivity=new_values(), *out=NULL;
    if (in && sensitivity) {
        IPortableDeviceValues_SetUnsignedIntegerValue(in,&SENSOR_PROPERTY_CURRENT_REPORT_INTERVAL,interval);
        for (int i=0;i<3;++i) {
            PROPVARIANT p; PropVariantInit(&p); p.vt=VT_R8; p.dblVal=0.0;
            IPortableDeviceValues_SetValue(sensitivity,fields[kind][i],&p);
        }
        IPortableDeviceValues_SetIPortableDeviceValuesValue(in,&SENSOR_PROPERTY_CHANGE_SENSITIVITY,sensitivity);
        ISensor_SetProperties(sensor,in,&out);
    }
    if (out) IPortableDeviceValues_Release(out);
    if (sensitivity) IPortableDeviceValues_Release(sensitivity);
    if (in) IPortableDeviceValues_Release(in);
}
static ULONG property_ui4(ISensor *sensor, REFPROPERTYKEY key) {
    PROPVARIANT p; PropVariantInit(&p);
    ULONG r=SUCCEEDED(ISensor_GetProperty(sensor,key,&p)) && p.vt==VT_UI4 ? p.ulVal : 0;
    PropVariantClear(&p);
    return r;
}
static ISensor *first_sensor(ISensorManager *manager, REFSENSOR_TYPE_ID type) {
    ISensorCollection *list=NULL; ISensor *sensor=NULL;
    if (SUCCEEDED(ISensorManager_GetSensorsByType(manager,type,&list))) {
        ULONG count=0;
        if (SUCCEEDED(ISensorCollection_GetCount(list,&count)) && count) ISensorCollection_GetAt(list,0,&sensor);
        ISensorCollection_Release(list);
    }
    return sensor;
}
/* Own thread: it joins the multithreaded apartment (the guest threads stay out of COM), so the
 * reports arrive on COM's threads without a message loop, and stays parked to keep it. */
static DWORD WINAPI sensor_thread(LPVOID started_event) {
    LONG result=-1;
    ISensorManager *manager=NULL;
    if (SUCCEEDED(CoInitializeEx(NULL,COINIT_MULTITHREADED)) &&
        SUCCEEDED(CoCreateInstance(&CLSID_SensorManager,NULL,CLSCTX_INPROC_SERVER,&IID_ISensorManager,(void **)&manager))) {
        ISensor *gyro=first_sensor(manager,&SENSOR_TYPE_GYROMETER_3D), *accel=first_sensor(manager,&SENSOR_TYPE_ACCELEROMETER_3D);
        ISensor *const sensors[2]={gyro,accel};
        for (int kind=0;kind<2;++kind) {
            if (!sensors[kind]) continue;
            const ULONG minimum=property_ui4(sensors[kind],&SENSOR_PROPERTY_MIN_REPORT_INTERVAL);
            configure(sensors[kind],kind,minimum>10 ? minimum : 10);
            ISensor_SetEventSink(sensors[kind],&sinks[kind].iface);
        }
        if (gyro) {
            BSTR name=NULL;
            ISensor_GetFriendlyName(gyro,&name);
            snprintf(description,sizeof description,"%ls, %lu ms%s",name ? name : L"gyro",
                     property_ui4(gyro,&SENSOR_PROPERTY_CURRENT_REPORT_INTERVAL),accel ? ", with accelerometer" : "");
            SysFreeString(name);
            result=1;
        }
    }
    InterlockedExchange(&ready,result);
    SetEvent((HANDLE)started_event);
    if (result>0) Sleep(INFINITE);
    return 0;
}
static BOOL CALLBACK start(PINIT_ONCE once, PVOID param, PVOID *context) {
    (void)once; (void)param; (void)context;
    QueryPerformanceFrequency(&qpf);
    const char *e=getenv("GOW3_HOST_MOTION");
    if (e && !strcmp(e,"0")) { ready=-1; return TRUE; }
    HANDLE done=CreateEventW(NULL,TRUE,FALSE,NULL);
    HANDLE thread=done ? CreateThread(NULL,0,sensor_thread,done,0,NULL) : NULL;
    if (thread) { WaitForSingleObject(done,2000); CloseHandle(thread); } /* the thread keeps the event */
    else { ready=-1; if (done) CloseHandle(done); }
    return TRUE;
}

int host_motion_read(float gyro[3], float accel[3]) {
    InitOnceExecuteOnce(&started,start,NULL,NULL);
    if (ready<=0) return 0;
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    double g[3], a[3];
    int have_accel;
    AcquireSRWLockShared(&lock);
    memcpy(g,data[KIND_GYRO].v,sizeof g); memcpy(a,data[KIND_ACCEL].v,sizeof a);
    const double gyro_age=data[KIND_GYRO].seen ? (double)(now.QuadPart-data[KIND_GYRO].at)/(double)qpf.QuadPart : 1e9;
    have_accel=data[KIND_ACCEL].seen;
    ReleaseSRWLockShared(&lock);
    /* Held still the driver goes quiet on its last reading (about 0.5 deg/s of hand tremor);
     * a slow steady turn keeps its value. */
    if (gyro_age>0.06 && sqrt(g[0]*g[0]+g[1]*g[1]+g[2]*g[2])<1.5) g[0]=g[1]=g[2]=0.0;
    const double rad=3.14159265358979323846/180.0, standard_gravity=9.80665;
    gyro[0]=(float)(g[0]*rad); gyro[1]=(float)(g[2]*rad); gyro[2]=(float)(-g[1]*rad);
    if (!have_accel || !accel) return 1;
    accel[0]=(float)(-a[0]*standard_gravity); accel[1]=(float)(-a[2]*standard_gravity); accel[2]=(float)(a[1]*standard_gravity);
    return 3;
}
const char *host_motion_describe(void) { return ready>0 ? description : NULL; }
#else
int host_motion_read(float gyro[3], float accel[3]) { (void)gyro; (void)accel; return 0; }
const char *host_motion_describe(void) { return NULL; }
#endif
