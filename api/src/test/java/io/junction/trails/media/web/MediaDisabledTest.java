package io.junction.trails.media.web;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = MediaController.class, properties = {"media.enabled=false", "spring.config.import="})
class MediaDisabledTest {
    @Autowired MockMvc mvc;

    @Test void baselineProfileDoesNotExposeTheNewEndpoint() throws Exception {
        mvc.perform(get("/api/places/00000000-0000-4000-8000-000000000001/media"))
                .andExpect(status().isNotFound());
    }
}
