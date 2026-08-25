#include <stdio.h>
#include <rtl-sdr.h>

// This function asks the system how many SDR devices are plugged in
int check_radio_count() {
    return rtlsdr_get_device_count();
}

// This function gets the official hardware name of the radio
const char* get_radio_name(int index) {
    if (index < rtlsdr_get_device_count()) {
        return rtlsdr_get_device_name(index);
    }
    return "No Radio Found";
}
