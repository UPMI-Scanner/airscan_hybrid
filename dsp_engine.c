#include <stdio.h>
#include <string.h>
#include <rtl-sdr.h>

int check_radio_count(void) {
    return (int)rtlsdr_get_device_count();
}

const char* get_radio_name(int index) {
    int count = (int)rtlsdr_get_device_count();
    if (index >= 0 && index < count) {
        return rtlsdr_get_device_name((uint32_t)index);
    }
    return "No Radio Found";
}

int get_radio_serial(int index, char* out_buf, int buf_len) {
    if (!out_buf || buf_len <= 0) return -1;
    out_buf[0] = '\0';
    int count = (int)rtlsdr_get_device_count();
    if (index < 0 || index >= count) return -1;

    char manufact[256] = {0}, product[256] = {0}, serial[256] = {0};
    if (rtlsdr_get_device_usb_strings((uint32_t)index, manufact, product, serial) == 0) {
        strncpy(out_buf, serial, (size_t)(buf_len - 1));
        out_buf[buf_len - 1] = '\0';
        return 0;
    }
    return -1;
}
